#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" filetags.py
    View, set, search, or remove xdg tags and comments from one or more files.
    With --nocolor and --search, it allows for operating on files with certain
    tags like this in BASH (where echo could be some other command):
        for fname in $(filetags -s python -n -R); do
            echo "Found $fname"
        done

        Or this:
            find -name "*.py" -exec filetags -n -s "script" "{}" +

    -Christopher Welborn 09-27-2015
"""

import inspect
import os
import re
import sys
from contextlib import suppress
from enum import Enum

import xattr
from colr import Colr as C
from docopt import docopt

NAME = 'File Tags'
VERSION = '0.1.0'
VERSIONSTR = '{} v. {}'.format(NAME, VERSION)
SCRIPT = os.path.split(os.path.abspath(sys.argv[0]))[1]
SCRIPTDIR = os.path.abspath(sys.path[0])

USAGESTR = """{versionstr}
    Usage:
        {script} -h | -v
        {script} [-A | -c | -t] (FILE... | [-R]) [-l] [-D | -F] [-I | -q] [-N]
        {script} -a tag (FILE... | [-R])         [-l] [-D | -F] [-I | -q] [-N]
        {script} -d tag (FILE... | [-R])         [-l] [-D | -F] [-I | -q] [-N]
        {script} -m comment (FILE... | [-R])     [-l] [-D | -F] [-I | -q] [-N]
        {script} -C [-c] (FILE... | [-R])        [-l] [-D | -F] [-I | -q] [-N]
        {script} -s pat [-c] [-n] [-r] [-R]      [-l] [-D | -F] [-I | -q] [-N]
        {script} -s pat [-c]  FILE... [-n] [-r]  [-l] [-D | -F] [-I | -q] [-N]

    Options:
        FILE                     : One or more file names.
                                   When not given, all paths in the current
                                   directory are used. If -R is given instead
                                   of FILES, the current directory is walked.
                                   Files and directories can be filtered
                                   with -F and -D.
        MSG                      : New comment message when setting comments.
        -a tag,--add tag         : Add a tag to existing tags.
                                   Several comma-separated tags can be used.
        -A,--attrs               : List all extended attributes.
        -c,--comment             : List file comments,
                                   search comments when -s is used,
                                   clear comments when -C is used.
        -C,--clear               : Clear all tags, or comments when -c is used.
        -d tag,--delete tag      : Remove an existing tag.
                                   Several comma-separated tags can be used.
        -D,--dirs                : Filter all file paths, use directories only.
        -F,--files               : Filter all file paths, use files only.
        -h,--help                : Show this help message.
        -I,--debug               : Print debugging info.
        -l,--symlinks            : Follow symlinks.
        -m msg,--setcomment msg  : Set the comment for a file.
        -n,--names               : Print names only when searching.
        -N,--nocolor             : Don't colorize output.
                                   This is automatically enabled when piping
                                   output.
        -q,--quiet               : Don't print anything to stdout.
                                   Error messages are still printed to stderr.
                                   This affects all commands, including the
                                   list commands.
        -r,--reverse             : Show files that don't match the search.
        -R,--recurse             : Recurse all sub-directories and files.
        -s pat,--search pat      : Search for text/regex pattern in tags,
                                   or comments when -c is used.
        -t,--tags                : List all tags.
        -v,--version             : Show version.

    The default action when no flag arguments are present is to list all tags.
    When no file names are given, files and directories in the current
    directory are used. When -R is given, the current directory is recursed.
""".format(script=SCRIPT, versionstr=VERSIONSTR)

# Global debug flag, set with --debug to print messages.
DEBUG = False
# Global silence flag, set with --quiet to avoid non-error messages.
QUIET = False
# OSError number for no data available (tag not available)
ENOCOMMENT = ENOTAGS = 61

# Disable colors when piping output.
NOCOLOR = not sys.stdout.isatty()
NOERRCOLOR = not sys.stderr.isatty()


def main(argd):
    """ Main entry point, expects doctopt arg dict as argd. """
    pathfilter = PathFilter.from_argd(argd)
    filenames = parse_filenames(
        argd['FILE'],
        pathfilter=pathfilter
    )
    if not filenames:
        filenames = get_filenames(
            recurse=argd['--recurse'],
            pathfilter=pathfilter)

    symlink = argd['--symlinks']

    if argd['--search']:
        return search(
            comments=argd['--comment'],
            filenames=filenames,
            pattern=argd['--search'],
            names_only=argd['--names'],
            reverse=argd['--reverse'],
            symlink=symlink
        )

    if argd['--add']:
        return add_tag(filenames, argd['--add'], symlink=symlink)
    elif argd['--attrs']:
        return list_attrs(filenames, symlink=symlink)
    elif argd['--clear']:
        if argd['--comment']:
            return clear_comment(filenames, symlink=symlink)
        return clear_tag(filenames, symlink=symlink)
    elif argd['--comment']:
        return list_comments(filenames, symlink=symlink)
    elif argd['--delete']:
        return remove_tag(filenames, argd['--delete'], symlink=symlink)
    elif argd['--setcomment']:
        return set_comment(filenames, argd['--setcomment'], symlink=symlink)
    elif argd['--tags']:
        return list_tags(filenames, symlink=symlink)

    # Default behavior
    return list_tags(filenames, symlink=symlink)


def add_file_tag(filename, taglist, symlink=False):
    """ Add a list of tags to a file.
        Returns the final tag list on success, or None on error.
    """
    existing = get_tags(filename, symlink=symlink)
    if existing is None:
        return None
    debug('Existing tags for {}: {!r}'.format(filename, existing))
    finaltags = existing[:]
    finaltags.extend(taglist)
    finaltags = sorted(set(finaltags))
    if finaltags == existing:
        debug('Tags already set to: {!r}'.format(finaltags))
        return finaltags

    if not set_tags(filename, sorted(set(finaltags)), symlink=symlink):
        return None
    return finaltags


def add_tag(filenames, tagstr, symlink=False):
    """ Add a tag or tags to file names.
        Return the number of errors.
    """
    errs = 0
    tags = parse_tagstr(tagstr)
    if not tags:
        print_err('No tags to set!: {}'.format(tagstr))
        return 1

    for filename in filenames:
        settags = add_file_tag(filename, tags, symlink=symlink)
        if settags is None:
            errs += 1
            continue
        status(format_file_tags(filename, settags, label='Set tags for'))
    return errs


def clear_comment(filenames, symlink=False):
    """ Clear all comments from file names.
        Return the number of errors.
    """
    return clear_xattr(filenames, attrname='user.xdg.comment', symlink=symlink)


def clear_tag(filenames, symlink=False):
    """ Clear all tags from file names.
        Return the number of errors.
    """
    return clear_xattr(filenames, attrname='user.xdg.tags', symlink=symlink)


def clear_xattr(filenames, attrname=None, symlink=False):
    """ Clear an entire extended attribute setting from file names.
        Return the number of errors.
    """
    if not attrname:
        print_err('No extended attribute name given!')
        return 1
    attrtype = attrname.split('.')[-1]
    errs = 0
    for filename in filenames:
        try:
            xattr.removexattr(filename, attrname)
        except EnvironmentError as ex:
            if ex.errno != ENOTAGS:
                print_err(
                    'Unable to clear {} for: {}'.format(attrtype, filename),
                    ex)
                errs += 1
                continue
            debug('{} already cleared: {}'.format(attrtype.title(), filename))
        # Tags were removed, or did not exist.
        status(format_file_name(
            filename,
            label='Cleared {} for'.format(attrtype)))
    return errs


def debug(*args, **kwargs):
    """ Print a message only if DEBUG is truthy. """
    if not (DEBUG and args):
        return None

    # Include parent class name when given.
    parent = kwargs.get('parent', None)
    with suppress(KeyError):
        kwargs.pop('parent')

    # Go back more than once when given.
    backlevel = kwargs.get('back', 1)
    with suppress(KeyError):
        kwargs.pop('back')

    frame = inspect.currentframe()
    # Go back a number of frames (usually 1).
    while backlevel > 0:
        frame = frame.f_back
        backlevel -= 1
    fname = os.path.split(frame.f_code.co_filename)[-1]
    lineno = frame.f_lineno
    if parent:
        func = '{}.{}'.format(parent.__class__.__name__, frame.f_code.co_name)
    else:
        func = frame.f_code.co_name

    # Patch args to stay compatible with print().
    pargs = list(args)
    if not NOCOLOR:
        # Colorize the line info.
        fname = C(fname, fore='yellow')
        lineno = C(str(lineno), fore='blue', style='bright')
        func = C(func, fore='magenta')

    lineinfo = '{}:{} {}(): '.format(fname, lineno, func).ljust(40)
    # Join and colorize the message.
    sep = kwargs.get('sep', None)
    if sep is not None:
        kwargs.pop('sep')
    else:
        sep = ' '
    if NOCOLOR:
        msg = ' '.join((lineinfo, sep.join(pargs)))
    else:
        msg = ' '.join((
            lineinfo,
            str(C(sep.join(pargs), fore='green'))
        ))
    # Format an exception.
    ex = kwargs.get('ex', None)
    if ex is not None:
        kwargs.pop('ex')
        if NOCOLOR:
            exmsg = str(ex)
        else:
            exmsg = str(C(str(ex), fore='red'))
        msg = '\n  '.join((msg, exmsg))
    return status(msg, **kwargs)


def format_file_attrs(filename, attrvals):
    """ Return a formatted file name and attribute name/values dict
        as str.
    """
    valfmt = '{:>24}: {}'.format
    if NOCOLOR:
        vals = '\n   '.join(
            valfmt(k, v) for k, v in attrvals.items()
        )
        if not vals:
            vals = '(none)'
    else:
        vals = '\n    '.join(
            valfmt(C(aname, fore='green'), C(aval, fore='cyan'))
            for aname, aval in attrvals.items()
        )
        if not vals:
            vals = C('none', fore='red').join('(', ')', style='bright')
    return '{}:\n    {}'.format(
        format_file_name(filename),
        vals)


def format_file_comment(filename, comment, label=None):
    """ Return a formatted file name and comment. """
    if not comment:
        if NOCOLOR:
            comment = '(empty)'
        else:
            comment = str(
                C('empty', fore='red').join('(', ')', style='bright')
            )
    return '{}:\n    {}'.format(
        format_file_name(filename, label=label),
        '\n    '.join(l for l in comment.splitlines())
    )


def format_file_name(filename, label=None):
    """ Return a formatted file name string. """
    if NOCOLOR:
        return filename

    style = 'bright' if os.path.isdir(filename) else 'normal'
    return ''.join((
        '{} '.format(label) if label else '',
        str(C(filename, fore='blue', style=style))
    ))


def format_file_tags(filename, taglist, label=None):
    """ Return a formatted file name and tags. """

    return '{}:\n    {}'.format(
        format_file_name(filename, label=label),
        format_tags(taglist)
    )


def format_file_cnt(filetype, total):
    """ Return a formatted search result string. """
    if total != 1:
        filetype = '{}s'.format(filetype)
    if NOCOLOR:
        return 'Found {} {}.'.format(total, filetype)

    return '{}.'.format(
        C(' ').join(
            C('Found', fore='cyan'),
            C(str(total), fore='blue', style='bright'),
            C(filetype, fore='cyan')
        )
    )


def format_tags(taglist):
    """ Format a list of tags into an indented string. """
    if NOCOLOR:
        tags = '\n    '.join(taglist)
        if not tags:
            return '(none)'
    else:
        tags = '\n    '.join(str(C(s, fore='cyan')) for s in taglist)
        if not tags:
            return C('none', fore='red').join('(', ')', style='bright')
    return tags


def get_attr_values(filename, symlink=False):
    """ Retrieve all attributes and values for a file name.
        Returns None on error, and a dict of {attrname: value} on success.
    """
    try:
        attrs = xattr.listxattr(filename, symlink=symlink)
    except EnvironmentError as ex:
        print_err(
            'Unable to list attributes for file: {}'.format(filename),
            ex)
        return None
    return {
        aname: get_value(filename, aname, symlink=symlink)
        for aname in attrs
    }


def get_comment(filename, symlink=False):
    """ Return the comment for a file.
        Returns None on error.
    """
    try:
        rawtext = xattr.getxattr(filename, 'user.xdg.comment', symlink=symlink)
    except EnvironmentError as ex:
        if ex.errno != ENOCOMMENT:
            print_err('Unable to get comment for: {}'.format(filename), ex)
            return None
        # Comment was blank/not set.
        return ''

    return rawtext.decode()


def get_filenames(recurse=False, pathfilter=None):
    """ Yield file paths in the current directory.
        If recurse is True, walk the current directory yielding paths.
    """
    pathfilter = pathfilter or PathFilter.none

    cwd = os.getcwd()
    debug('\n'.join((
        'Getting file names from: {}',
        '              Filtering: {}'
    )).format(cwd, pathfilter))

    cnt = 0
    if recurse:
        try:
            for root, dirs, files in os.walk(cwd):
                if pathfilter != PathFilter.files:
                    for dirname in dirs:
                        cnt += 1
                        yield os.path.join(root, dirname)
                if pathfilter != PathFilter.dirs:
                    for filename in files:
                        cnt += 1
                        yield os.path.join(root, filename)
        except EnvironmentError as ex:
            print_err('Unable to walk directory: {}'.format(cwd), ex)
    else:
        filterpath = {
            PathFilter.none: lambda s: True,
            PathFilter.dirs: os.path.isdir,
            PathFilter.files: os.path.isfile
        }.get(pathfilter)

        try:
            for path in os.listdir(cwd):
                fullpath = os.path.join(cwd, path)
                if filterpath(fullpath):
                    cnt += 1
                    yield fullpath
        except EnvironmentError as ex:
            print_err('Unable to list directory: {}'.format(cwd), ex)
    status('\n{}'.format(format_file_cnt('file', cnt)))


def get_tags(filename, symlink=False):
    """ Return a list of all file tags for a file.
        Returns None on error, and a list for success (even an empty list).
    """
    try:
        tagstr = xattr.getxattr(filename, 'user.xdg.tags', symlink=symlink)
    except EnvironmentError as ex:
        if ex.errno != ENOTAGS:
            print_err('Error getting tags for: {}'.format(filename), ex)
            return None
        debug('No tags for: {}'.format(filename), ex=ex)
        return []
    tags = (s.strip() for s in tagstr.decode().split(','))
    return sorted(s for s in tags if s)


def get_value(filename, attrname, symlink=False):
    """ Retrieve the value for a known attribute name. """
    try:
        val = xattr.getxattr(filename, attrname, symlink=symlink)
    except EnvironmentError as ex:
        print_err(
            'Unable to get value for `{}` in: {}'.format(attrname, filename),
            ex)
        return ''
    return val.decode()


def list_attrs(filenames, symlink=False):
    """ List raw attributes and values for file names.
        Returns the number of errors.
    """
    return list_action(
        filenames,
        get_attr_values,
        format_file_attrs,
        symlink=symlink)


def list_action(filenames, value_func, format_func, symlink=False):
    """ Run an action for the 'list' commands.
        Arguments:
            filenames    : An iterable of valid file names.
            value_func   : A function to return values for the filename,
                           which is passed on to the format_func.
                           See: get_tags() and get_attr_values()
            format_func  : A function to format a filename and values.
                           See: format_file_attrs() and format_file_tags()
            symlink      : Whether to follow symlinks, a kwarg for
                           value_func.

        Returns the number of errors.
    """
    errs = 0
    for filename in filenames:
        values = value_func(filename, symlink=symlink)
        if values is None:
            errs += 1
            continue
        status(format_func(filename, values))
    return errs


def list_comments(filenames, symlink=False):
    """ List comments for file names.
        Returns the number of errors.
    """
    return list_action(
        filenames,
        get_comment,
        format_file_comment,
        symlink=symlink)


def list_tags(filenames, symlink=False):
    """ List all file tags for file names.
        Returns the number of errors.
    """
    return list_action(
        filenames,
        get_tags,
        format_file_tags,
        symlink=symlink)


def parse_filenames(filenames, pathfilter=None):
    """ Ensure all file names have an absolute path.
        Print any non-existent files.
        Returns a set of full paths.
    """
    pathfilter = pathfilter or PathFilter.none
    filterpath = {
        PathFilter.none: lambda s: True,
        PathFilter.dirs: os.path.isdir,
        PathFilter.files: os.path.isfile
    }.get(pathfilter)

    validnames = set()
    for filename in filenames:
        fullpath = os.path.abspath(filename)
        if not os.path.exists(fullpath):
            print_err('File does not exist: {}'.format(fullpath))
        elif filterpath(fullpath):
            validnames.add(fullpath)
        else:
            raise RuntimeError('Invalid PathFilter enum value!')
    debug('User file names: {}, Filter: {}'.format(
        len(validnames),
        pathfilter))
    return validnames


def parse_tagstr(tagstr):
    """ Return a tuple of tag names from a comma-separated string. """
    rawnames = (s.strip() for s in tagstr.split(','))
    return tuple(s for s in rawnames if s)


def print_err(msg=None, ex=None):
    """ Print an error message.
        If an Exception is passed in for `ex`, it's message is also printed.
    """
    if msg:
        errmsg = msg if NOERRCOLOR else C(msg, fore='red')
        sys.stderr.write('{}\n'.format(errmsg))
    if ex is not None:
        if NOERRCOLOR:
            exmsg = str(ex)
        else:
            exmsg = C(str(ex), fore='red', style='bright')
        sys.stderr.write('    {}\n'.format(exmsg))
    sys.stderr.flush()
    return None


def remove_comment(filenames, symlink=False):
    """ Remove the comment from file names.
        Returns the number of errors.
    """
    errs = 0
    for filename in filenames:
        try:
            xattr.removexattr(filename, 'user.xdg.comment', symlink=symlink)
        except EnvironmentError as ex:
            if ex.errno != ENOCOMMENT:
                print_err(
                    'Unable to remove comment from: {}'.format(filename),
                    ex)
                errs += 1
                continue
            # Comment was not available.
        status(format_file_name(filename, label='Cleared comment for'))

    return errs


def remove_file_tag(filename, taglist, symlink=False):
    """ Remove a list of tags from a file name.
        Returns the final tag list on success, or None on error.
    """
    filetags = get_tags(filename, symlink=symlink)
    if filetags is None:
        return None
    if not filetags:
        debug('No tags to remove for: {}'.format(filename))
        return []
    for tagname in taglist:
        try:
            filetags.remove(tagname)
        except ValueError:
            debug('{}: Tag did not exist: {}'.format(filename, tagname))
    if not set_tags(filename, filetags):
        return None

    return filetags


def remove_tag(filenames, tagstr, symlink=False):
    """ Remove a tag or tags from file names.
        Returns the number of errors.
    """
    errs = 0
    taglist = parse_tagstr(tagstr)
    if not taglist:
        print_err('No tags to remove!: {}'.format(tagstr))
        return 1

    for filename in filenames:
        finaltags = remove_file_tag(filename, taglist, symlink=symlink)
        if finaltags is None:
            errs += 1
            continue
        status(format_file_tags(filename, finaltags, label='Set tags for'))

    return errs


def search(
        comments=False, filenames=None, pattern=None,
        names_only=False, reverse=False, symlink=False):
    """ Run one of the search functions on comments/tags.
        If no file names are given, the current directory is used.
        If recurse is True, the current directory is walked.
    """
    pat = try_repat(pattern)
    if pat is None:
        return 1

    searchargs = {
        'names_only': names_only,
        'reverse': reverse,
        'symlink': symlink
    }
    debug('search args: {!r}'.format(searchargs))
    if comments:
        return search_comments(filenames, pat, **searchargs)
    return search_tags(filenames, pat, **searchargs)


def search_comments(
        filenames, repat, names_only=False, reverse=False, symlink=False):
    """ Search comments for a pattern.
        Returns the number of errors.
    """
    debug('Running comment search for: {}'.format(repat.pattern))
    found = 0
    errs = 0
    if reverse:
        debug('Using reverse match.')
        is_match = lambda rematch: rematch is None
    else:
        is_match = lambda rematch: rematch is not None

    for filename in filenames:
        comment = get_comment(filename, symlink=symlink)
        if comment is None:
            errs += 1
            continue

        # Empty comments are still valuable for patterns like: ^$
        # ..and reverse/normal patterns like: ^.+$
        rematch = repat.search(comment)
        if is_match(rematch):
            if names_only:
                status(format_file_name(filename))
            else:
                status(format_file_comment(filename, comment))
            found += 1

    if not names_only:
        status('\n{}'.format(format_file_cnt('comment', found)))
    return errs


def search_tags(
        filenames, repat, names_only=False, reverse=False, symlink=False):
    """ Search comments for a pattern.
        If no file names are given, the current directory is used.
        If recurse is True, the current directory is walked.
        Returns the number of errors.
    """
    debug('Running tag search for: {}'.format(repat.pattern))

    found = 0
    errs = 0

    for filename in filenames:
        tags = get_tags(filename, symlink=symlink)
        if tags is None:
            errs += 1
            continue

        if tag_match(repat, tags, reverse=reverse):
            found += 1
            if names_only:
                status(format_file_name(filename))
            else:
                status(format_file_tags(filename, tags))

    if not names_only:
        status('\n{}'.format(format_file_cnt('tag', found)))
    return errs


def set_comment(filenames, comment, symlink=False):
    """ Set the comment for file names.
        Returns the number of errors.
    """
    errs = 0
    for filename in filenames:
        newcomment = set_file_comment(filename, comment, symlink=symlink)
        if newcomment is None:
            errs += 1
            continue
        status(format_file_comment(filename, comment, label='Set comment for'))
    return errs


def set_file_comment(filename, comment, symlink=False):
    """ Set the comment attribute for a file.
        Returns the new comment on success, or None on error.
    """
    try:
        xattr.setxattr(
            filename,
            'user.xdg.comment',
            comment.encode(),
            symlink=symlink)
    except EnvironmentError as ex:
        print_err('Unable to set comment for: {}'.format(filename), ex)
        return None
    return comment


def set_tags(filename, taglist, symlink=False):
    """ Set a list of tags for a file name.
        Returns True for success, or False on error.
    """

    tagstr = ','.join(taglist).encode()
    try:
        xattr.setxattr(filename, 'user.xdg.tags', tagstr, symlink=symlink)
    except EnvironmentError as ex:
        print_err('Error setting tags for: {}'.format(filename), ex)
        return False

    return True


def status(msg, **kwargs):
    """ Print a message, unless QUIET is set (with --quiet).
        kwargs are for print().
    """
    if QUIET:
        return None
    return print(msg, **kwargs)


def tag_match(repat, taglist, reverse=False):
    """ Return true if a regex pattern matches any of the tags in the taglist.
        If reverse is used, return True when none of the tags match.
    """
    if reverse:
        if not taglist:
            return repat.search('') is None
        return all((repat.search(s) is None) for s in taglist)
    if not taglist:
        return repat.search('') is not None
    return any((repat.search(s) is not None) for s in taglist)


def try_repat(s):
    """ Try compiling a regex pattern.
        On failure, print any errors and return None.
        Return the compiled regex pattern on success.
    """
    try:
        pat = re.compile(s)
    except re.error as ex:
        print_err('Invalid pattern: {}'.format(s), ex)
        return None
    return pat


class PathFilter(Enum):

    """ File path filter setting. """
    none = 0
    dirs = 1
    files = 2

    def __str__(self):
        """ Human-friendly string representation for a PathFilter. """
        return {
            PathFilter.none.value: 'None',
            PathFilter.dirs.value: 'Directories',
            PathFilter.files.value: 'Files'
        }.get(self.value)

    @classmethod
    def from_argd(cls, argd):
        """ Return a PathFilter based on docopt's arg dict. """
        if argd['--dirs']:
            return cls.dirs
        if argd['--files']:
            return cls.files
        return cls.none


if __name__ == '__main__':
    ARGD = docopt(USAGESTR, version=VERSIONSTR)
    DEBUG = ARGD['--debug']

    QUIET = ARGD['--quiet']
    if ARGD['--nocolor']:
        # Override automatic detection.
        NOCOLOR = NOERRCOLOR = True

    if DEBUG:
        # This should never be used in non-debug mode.
        import json

        def json_str(obj, label=None, sort_keys=False):
            """ Return a json dump of an object, for debugging. """
            if label:
                return '\n'.join((
                    label,
                    json.dumps(obj, indent=8, sort_keys=sort_keys)
                ))
            return json.dumps(obj, indent=4, sort_keys=sort_keys)
        print(json_str(ARGD, label='Docopt Args:'))

    MAINRET = main(ARGD)
    sys.exit(MAINRET)
