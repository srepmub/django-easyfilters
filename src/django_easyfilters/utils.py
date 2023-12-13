try:
    from django.db.models.constants import LOOKUP_SEP
except ImportError:  # Django < 1.5 fallback
    from django.db.models.sql.constants import LOOKUP_SEP
from django.db.models import ManyToManyField
from six import PY3


def python_2_unicode_compatible(klass):  # Copied from Django 1.5
    """
    A decorator that defines __unicode__ and __str__ methods under Python 2.
    Under Python 3 it does nothing.

    To support Python 2 and 3 with a single code base, define a __str__ method
    returning text and apply this decorator to the class.
    """
    if not PY3:
        klass.__unicode__ = klass.__str__
        klass.__str__ = lambda self: self.__unicode__().encode('utf-8')
    return klass


def get_model_field(model, f):
    parts = f.split(LOOKUP_SEP)
    opts = model._meta
    for name in parts[:-1]:
        rel = opts.get_field(name)
        model = rel.related_model
        opts = model._meta
    rel = opts.get_field(parts[-1])
    m2m = isinstance(rel, ManyToManyField)
    return rel, m2m
