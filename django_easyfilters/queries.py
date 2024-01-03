from collections import OrderedDict

from django import VERSION
from django.db import models


def value_counts(qs, fieldname):
    """
    Performs a simple query returning the count of each value of
    the field 'fieldname' in the QuerySet, returning the results
    as a SortedDict of value: count
    """
    values_counts = qs.filter(**{
        fieldname+"__isnull": False
    }).values_list(fieldname)\
        .order_by(fieldname)\
        .annotate(models.Count(fieldname))
    count_dict = OrderedDict()
    null_count = qs.filter(**{fieldname+"__isnull": True}).count()
    if null_count:
        count_dict[None] = null_count
    for val, count in values_counts:
        count_dict[val] = count
    return count_dict


def numeric_range_counts(qs, fieldname, ranges):
    qs = qs.annotate(
        added_updated = models.Case(
            *[models.When(**{f'{fieldname}__range': [r[0], r[1]], 'then': models.Value(i)})
                 for (i, r) in enumerate(ranges)]
        ),
    ).values('added_updated').order_by('added_updated').annotate(count=models.Count('added_updated'))

    count_dict = OrderedDict()
    for row in qs:
        val = row['added_updated']
        if val is not None:
            count = row['count']
            try:
                r = ranges[val]
            except IndexError:
                # Include in the top range - this could be a rounding error
                r = ranges[-1]
            count_dict[r] = count
    return count_dict
