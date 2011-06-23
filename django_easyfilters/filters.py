from collections import namedtuple
import operator

from django.db import models
from django.utils.datastructures import SortedDict

FILTER_ADD = 'add'
FILTER_REMOVE = 'remove'
FILTER_ONLY_CHOICE = 'only'

FilterChoice = namedtuple('FilterChoice', 'label count params link_type')


class FilterOptions(object):
    """
    Defines some common options for all Filters.

    A FilterOption instance can be used when defining the 'fields' attribute of
    a FilterSet. The actual choice of Filter subclass will be done by the
    FilterSet in this case.
    """
    def __init__(self, query_param=None, order_by_count=False):
        self.query_param = query_param
        self.order_by_count = order_by_count


class Filter(FilterOptions):
    """
    A Filter creates links/URLs that correspond to some DB filtering,
    and can apply the information from a URL to filter a QuerySet.
    """
    def __init__(self, field, model, **kwargs):
        # State: Filter objects are created as class attributes of FilterSets,
        # and so cannot carry any request specific state. They only have
        # configuration information.
        self.field = field
        self.model = model
        if kwargs.get('query_param', None) is None:
            kwargs['query_param'] = field
        self.field_obj = self.model._meta.get_field(self.field)
        super(Filter, self).__init__(**kwargs)

    def apply_filter(self, qs, params):
        p_val = self.choices_from_params(params)
        while len(p_val) > 0:
            qs = qs.filter(**{self.field: p_val.pop()})
        return qs

    def to_python(self, param):
        return self.field_obj.to_python(param)

    def choices_from_params(self, params):
        """
        For the params passed in (i.e. from query string), retrive a list of
        already 'chosen' options.
        """
        return [self.to_python(i) for i in params.getlist(self.query_param)]

    def param_from_choices(self, choices):
        """
        For a list of choices, return the parameter that should be created.
        """
        return map(unicode, choices)

    def build_params(self, params, add=None, remove=None):
        params = params.copy()
        chosen = self.choices_from_params(params)
        if remove:
            chosen.remove(remove)
        else:
            if add not in chosen:
                chosen.append(add)
        if chosen:
            params.setlist(self.query_param, self.param_from_choices(chosen))
        else:
            del params[self.query_param]
        params.pop('page', None) # links should reset paging
        return params

    def normalize_add_choices(self, choices):
        if len(choices) == 1:
            # No point giving people a choice of one
            choices = [FilterChoice(label=choices[0].label,
                                    count=choices[0].count,
                                    link_type=FILTER_ONLY_CHOICE,
                                    params=None)]
        return choices

    def sort_choices(self, qs, params, choices):
        """
        Sorts the choices by applying order_by_count if applicable.

        See also sort_choices_custom.
        """
        if self.order_by_count:
            choices.sort(key=operator.attrgetter('count'), reverse=True)
        else:
            choices = self.sort_choices_custom(qs, params, choices)
        return choices

    def sort_choices_custom(self, qs, params, choices):
        """
        Override this to provide a custom sorting method for a field. If sorting
        can be better done in the DB, it should be done in the get_choices_add
        method.
        """
        return choices

    def display_choice(self, choice):
        retval = unicode(choice)
        if retval == u'':
            return u'(empty)'
        else:
            return retval

    def get_choices(self, qs, params):
        """
        Returns a list of namedtuples containing (label (as a string), count,
        params)
        """
        raise NotImplementedError()


class SingleValueFilterMixin(object):

    def get_values_counts(self, qs, params):
        """
        Returns a SortedDict dictionary of {value: count}.

        The order is the underlying order produced by sorting ascending on the
        DB field.
        """
        values_counts = qs.values_list(self.field).order_by(self.field).annotate(models.Count(self.field))

        count_dict = SortedDict()
        for val, count in values_counts:
            count_dict[val] = count
        return count_dict

    def get_choices(self, qs, params):
        choices_remove = self.get_choices_remove(qs, params)
        if len(choices_remove) > 0:
            return choices_remove
        else:
            choices_add = self.normalize_add_choices(self.get_choices_add(qs, params))
            return self.sort_choices(qs, params, choices_add)

    def get_choices_add(self, qs, params):
        raise NotImplementedError()

    def get_choices_remove(self, qs, params):
        choices = self.choices_from_params(params)
        return [FilterChoice(self.display_choice(choice),
                             None, # Don't need count for removing
                             self.build_params(params, remove=choice),
                             FILTER_REMOVE)
                for choice in choices]


class ValuesFilter(SingleValueFilterMixin, Filter):
    """
    Fallback Filter for various kinds of simple values.
    """
    def get_choices_add(self, qs, params):
        """
        Called by 'get_choices', this is usually the one to override.
        """
        count_dict = self.get_values_counts(qs, params)
        return [FilterChoice(self.display_choice(val),
                             count,
                             self.build_params(params, add=val),
                             FILTER_ADD)
                for val, count in count_dict.items()]


class ChoicesFilter(ValuesFilter):
    """
    Filter for fields that have 'choices' defined.
    """
    # Need to do the following:
    # 1) ensure we only display options that are in 'choices'
    # 2) ensure the order is the same as in choices
    # 3) make display value = the second element in choices' tuples.
    def __init__(self, *args, **kwargs):
        super(ChoicesFilter, self).__init__(*args, **kwargs)
        # For performance we cache this rather than build in
        self.choices_dict = dict(self.field_obj.flatchoices)

    def display_choice(self, choice):
        # 3) above
        return self.choices_dict.get(choice, choice)

    def get_choices_add(self, qs, params):
        count_dict = self.get_values_counts(qs, params)
        choices = []
        for val, display in self.field_obj.choices:
            # 1), 2) above
            if val in count_dict:
                # We could use the value 'display' here, but for consistency
                # call display_choice() in case it is overriden.
                choices.append(FilterChoice(self.display_choice(val),
                                            count_dict[val],
                                            self.build_params(params, add=val),
                                            FILTER_ADD))
        return choices


class ForeignKeyFilter(SingleValueFilterMixin, Filter):
    """
    Filter for ForeignKey fields.
    """
    def __init__(self, *args, **kwargs):
        super(ForeignKeyFilter, self).__init__(*args, **kwargs)
        self.rel_model = self.field_obj.rel.to
        self.rel_field = self.field_obj.rel.get_related_field()

    def display_choice(self, choice):
        lookup = {self.rel_field.name: choice}
        return unicode(self.rel_model.objects.get(**lookup))

    def get_choices_add(self, qs, params):
        count_dict = self.get_values_counts(qs, params)
        lookup = {self.rel_field.name + '__in': count_dict.keys()}
        objs = self.rel_model.objects.filter(**lookup)
        choices = []

        for o in objs:
            pk = getattr(o, self.rel_field.attname)
            choices.append(FilterChoice(unicode(o),
                                        count_dict[pk],
                                        self.build_params(params, add=pk),
                                        FILTER_ADD))
        return choices


class MultiValueFilterMixin(object):

    def get_choices(self, qs, params):
        # In general, can filter multiple times, so we can have multiple remove
        # links, and multiple add links, at the same time.
        choices_remove = self.get_choices_remove(qs, params)
        choices_add = self.normalize_add_choices(self.get_choices_add(qs, params))
        choices_add = self.sort_choices(qs, params, choices_add)
        return choices_remove + choices_add


class ManyToManyFilter(MultiValueFilterMixin, Filter):
    def __init__(self, *args, **kwargs):
        super(ManyToManyFilter, self).__init__(*args, **kwargs)
        self.rel_model = self.field_obj.rel.to

    def to_python(self, param):
        return self.field_obj.rel.get_related_field().to_python(param)

    def get_choices_add(self, qs, params):
        # It is easiest to base queries around the intermediate table, in order
        # to get counts.
        through = self.field_obj.rel.through
        rel_model = self.rel_model

        assert rel_model != self.model, "Can't cope with this yet..."

        fkey_to_this_table = [f for f in through._meta.fields
                              if f.rel is not None and f.rel.to is self.model][0]
        fkey_to_other_table = [f for f in through._meta.fields
                               if f.rel is not None and f.rel.to is rel_model][0]

        # We need to limit items by what is in the main QuerySet (which might
        # already be filtered).
        main_filter = {fkey_to_this_table.name + '__in':qs}
        m2m_objs = through.objects.filter(**main_filter)

        # We need to exclude items in other table that we have already filtered
        # on, because they are not interesting.
        exclude_filter = {fkey_to_other_table.name + '__in': self.choices_from_params(params)}
        m2m_objs = m2m_objs.exclude(**exclude_filter)

        # Now get counts:
        field_name = fkey_to_other_table.name
        values_counts = m2m_objs.values_list(field_name).order_by(field_name).annotate(models.Count(field_name))

        count_dict = SortedDict()
        for val, count in values_counts:
            count_dict[val] = count

        # Now, need to lookup objects on related table, to display them.
        objs = rel_model.objects.filter(pk__in=count_dict.keys())

        choices = []
        for o in objs:
            pk = o.pk
            choices.append(FilterChoice(unicode(o),
                                        count_dict[pk],
                                        self.build_params(params, add=pk),
                                        FILTER_ADD))
        return choices


    def get_choices_remove(self, qs, params):
        choices = self.choices_from_params(params)
        # Do a query in bulk to get objs corresponding to choices.
        objs = self.rel_model.objects.filter(pk__in=choices)

        # We want to preserve order of items in params, so use a dict:
        obj_dict = dict([(obj.pk, obj) for obj in objs])
        return [FilterChoice(unicode(obj_dict[choice]),
                             None, # Don't need count for removing
                             self.build_params(params, remove=choice),
                             FILTER_REMOVE)
                for choice in choices]