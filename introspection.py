#!/usr/bin/env python3
"""Routines for object examination.

This script is copyright 2017-20 by Patrick Mooney. It is licensed under the GNU
GPL, either version 3 or (at your option) any later version. See the file
LICENSE.md for details.
"""


import pprint
import inspect
import pickle


def dump_str(obj):
    """Get a textual catalog of object attributes.

    Based on https://stackoverflow.com/a/192184/5562328
    """
    object_representation = {}.copy()
    for attr in dir(obj):
        object_representation[attr] = getattr(obj, attr)
    return pprint.pformat(object_representation)


def dump(obj):
    """Just dump a string representation of all object attributes to stdout."""
    pprint.pprint(dump_str(obj))


def unpickle_and_dump(the_file):
    """Like dump(), but unpickles the contents of a file, then dumps what comes out."""
    with open(the_file, 'rb') as f:
        data = pickle.load(f)
    dump(data)
    pprint.pprint(data)


def object_size_estimate(obj):
    """Yeah, I keep meaning to actually write this. Sigh."""
    pass


def class_methods_in_module(module_name, class_names=True, include_leading_underscores=False):
    """Get all class methods from a module."""
    ret = set()
    classes = inspect.getmembers(module_name, inspect.isclass)
    for c in classes:
        for m in c[1].__dict__:
            if include_leading_underscores or not m.startswith('_'):
                if class_names: ret |= set(["%s.%s" % (c[0], m)])
                else: ret.add(str(m))
    return ret


if __name__ == "__main__":
    import creatures
    pprint.pprint(class_methods_in_module(creatures, include_leading_underscores=True))
