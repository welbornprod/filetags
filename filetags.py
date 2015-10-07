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
import errno
import inspect
import os
import re
import sys
from contextlib import suppress
from enum import Enum
from pathlib import Path

import xattr
from colr import Colr as C
from docopt import docopt

NAME = 'File Tags'
VERSION = '0.2.0'
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
                                   If - is given as a file name, stdin is read
                                   and each line will be used as a file name.
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

    Editor.follow_symlinks = argd['--symlinks']

    if argd['--search']:
        return search(
            comments=argd['--comment'],
            filenames=filenames,
            pattern=argd['--search'],
            names_only=argd['--names'],
            reverse=argd['--reverse']
        )

    if argd['--add']:
        return add_tag(filenames, argd['--add'])
    elif argd['--attrs']:
        return list_attrs(filenames)
    elif argd['--clear']:
        if argd['--comment']:
            return clear_comment(filenames)
        return clear_tag(filenames)
    elif argd['--comment']:
        return list_comments(filenames)
    elif argd['--delete']:
        return remove_tag(filenames, argd['--delete'])
    elif argd['--setcomment']:
        return set_comment(filenames, argd['--setcomment'])
    elif argd['--tags']:
        return list_tags(filenames)

    # Default behavior
    return list_tags(filenames)


def add_tag(filenames, tagstr):
    """ Add a tag or tags to file names.
        Return the number of errors.
    """
    errs = 0
    try:
        tags = Editor.parse_tagstr(tagstr)
    except ValueError as ex:
        print_err(ex)
        return 1

    for filename in filenames:
        editor = Editor(filename)
        try:
            settags = editor.add_tags(tags)
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue
        status(
            format_file_tags(
                editor.filepath,
                settags,
                label='Set tags for'))
    return errs


def clear_comment(filenames):
    """ Clear all comments from file names.
        Return the number of errors.
    """
    return clear_xattr(
        filenames,
        attrname=Editor.attr_comment)


def clear_tag(filenames):
    """ Clear all tags from file names.
        Return the number of errors.
    """
    return clear_xattr(
        filenames,
        attrname=Editor.attr_tags)


def clear_xattr(filenames, attrname=None):
    """ Clear an entire extended attribute setting from file names.
        Return the number of errors.
    """
    if not attrname:
        print_err('No extended attribute name given!')
        return 1
    attrtype = attrname.split('.')[-1]
    errs = 0
    for filename in filenames:
        editor = Editor(filename)
        try:
            editor.remove_attr(attrname)
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue

        # Tags were removed, or did not exist.
        status(format_file_name(
            editor.filepath,
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
    valfmt = '{:>35}: {}'.format
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


def list_attrs(filenames):
    """ List raw attributes and values for file names.
        Returns the number of errors.
    """
    return list_action(
        filenames,
        'get_attrs',
        format_file_attrs)


def list_action(filenames, value_func_name, format_func):
    """ Run an action for the 'list' commands.
        Arguments:
            filenames         : An iterable of valid file names.
            values_func_name  : Name of Editor method to get values.
            format_func       : A function to format a filename and values.
                                See: format_file_attrs() and format_file_tags()
            symlink           : Whether to follow symlinks, a kwarg for
                                value_func.

        Returns the number of errors.
    """
    errs = 0
    for filename in filenames:
        editor = Editor(filename)
        value_func = getattr(editor, value_func_name)
        try:
            values = value_func()
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue
        status(format_func(editor.filepath, values))
    return errs


def list_comments(filenames):
    """ List comments for file names.
        Returns the number of errors.
    """
    return list_action(
        filenames,
        'get_comment',
        format_file_comment)


def list_tags(filenames):
    """ List all file tags for file names.
        Returns the number of errors.
    """
    return list_action(
        filenames,
        'get_tags',
        format_file_tags)


def parse_filenames(filenames, pathfilter=None, nostdin=False):
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
        if filename == '-':
            # Read stdin if not done already.
            if nostdin:
                continue
            stdin_valid = parse_stdin_filenames()
            if stdin_valid:
                validnames.update(stdin_valid)
                continue
            # No names were in stdin.
            print_err('\nNo valid file names to work with from stdin.')
            sys.exit(1)

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


def parse_stdin_filenames():
    """ Read file names from stdin. One file name per line. """
    if sys.stdin.isatty() and sys.stdout.isatty():
        print('\nReading from stdin until end of file (Ctrl + D)...\n')

    return parse_filenames(
        set(s.strip() for s in sys.stdin.readlines()),
        nostdin=True
    )


def print_err(msg=None, ex=None):
    """ Print an error message.
        If an Exception is passed in for `ex`, it's message is also printed.
    """
    if msg:
        if isinstance(msg, Exception):
            # Shortcut use, like print_err(ex=msg).
            msglines = str(msg).splitlines()
            if len(msglines) > 1:
                msg = '\n'.join(msglines[:-1])
                ex = msglines[-1]

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


def remove_comment(filenames):
    """ Remove the comment from file names.
        Returns the number of errors.
    """
    errs = 0
    for filename in filenames:
        editor = Editor(filename)
        try:
            editor.clear_comment()
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue
            # Comment was not available.
        status(format_file_name(editor.filepath, label='Cleared comment for'))

    return errs


def remove_tag(filenames, tagstr):
    """ Remove a tag or tags from file names.
        Returns the number of errors.
    """
    errs = 0
    try:
        taglist = Editor.parse_tagstr(tagstr)
    except ValueError as ex:
        print_err(ex)
        return 1

    for filename in filenames:
        editor = Editor(filename)
        try:
            finaltags = editor.remove_tags(taglist)
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue
        status(format_file_tags(filename, finaltags, label='Set tags for'))

    return errs


def search(
        comments=False, filenames=None, pattern=None,
        names_only=False, reverse=False):
    """ Run one of the search functions on comments/tags.
        If no file names are given, the current directory is used.
        If recurse is True, the current directory is walked.
    """
    pat = try_repat(pattern)
    if pat is None:
        return 1

    searchargs = {
        'names_only': names_only,
        'reverse': reverse
    }
    debug('search args: {!r}'.format(searchargs))
    if comments:
        return search_comments(filenames, pat, **searchargs)
    return search_tags(filenames, pat, **searchargs)


def search_comments(
        filenames, repat, names_only=False, reverse=False):
    """ Search comments for a pattern.
        Returns the number of errors.
    """
    debug('Running comment search for: {}'.format(repat.pattern))
    found = 0
    errs = 0
    if reverse:
        debug('Using reverse match.')

    for filename in filenames:
        editor = Editor(filename)
        try:
            comment = editor.match_comment(repat, reverse=reverse)
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue

        if comment is not None:
            if names_only:
                status(format_file_name(editor.filepath))
            else:
                status(format_file_comment(editor.filepath, comment))
            found += 1

    if not names_only:
        status('\n{}'.format(format_file_cnt('comment', found)))
    return errs


def search_tags(
        filenames, repat, names_only=False, reverse=False):
    """ Search comments for a pattern.
        If no file names are given, the current directory is used.
        If recurse is True, the current directory is walked.
        Returns the number of errors.
    """
    debug('Running tag search for: {}'.format(repat.pattern))

    found = 0
    errs = 0

    for filename in filenames:
        editor = Editor(filename)
        try:
            tags = editor.match_tags(repat, reverse=reverse)
        except Editor.AttrError as ex:
            print_err(ex)
            errs += 1
            continue

        if tags is not None:
            found += 1
            if names_only:
                status(format_file_name(editor.filepath))
            else:
                status(format_file_tags(editor.filepath, tags))

    if not names_only:
        status('\n{}'.format(format_file_cnt('tag', found)))
    return errs


def set_comment(filenames, comment):
    """ Set the comment for file names.
        Returns the number of errors.
    """
    errs = 0
    for filename in filenames:
        editor = Editor(filename)
        try:
            newcomment = editor.set_comment(comment)
        except Editor.AttrError as ex:
            errs += 1
            print_err(ex)
        else:
            status(
                format_file_comment(
                    editor.filepath,
                    newcomment,
                    label='Set comment for'))
    return errs


def status(msg, **kwargs):
    """ Print a message, unless QUIET is set (with --quiet).
        kwargs are for print().
    """
    if QUIET:
        return None
    return print(msg, **kwargs)


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


class Editor(object):
    """ Holds information and helper methods for a single file and it's
        tags/comments.
        __init__ possibly raises FileNotFoundError or ValueError (for no path).

        Tags are comma-separated by default, and encoded using the system's
        default encoding. This can be subclassed to handle different formats by
        overriding the class methods parse_tagstr() and parse_taglist().
        The encoding can be changed by setting Editor.encoding.
        If all that is needed is a different separator, then Editor.tag_sep
        can be set.
        The default attributes are 'user.xdg.tags' and
        'user.xdg.comment', but they can also be changed by setting
        Editor.attr_tags and Editor.attr_comment.
        Finally, if you would like xattr to follow symlinks then set
        Editor.follow_symlinks to True.

        If you would like AttrError to be raised for missing attributes,
        set Editor.errno_nodata to 0, or some other non-existent number in the
        errno module.

        Instance Attributes:
            follow_symlinks  : Passed to xattr, whether to follow symlinks.
            path             : Resolved pathlib.Path().
            filepath         : File path string (str(self.path)).
            tags             : List of tags, or [].
            comment          : String containing the comment, or ''.
    """
    # Attributes to use for retrieving tags/comments.
    attr_tags = 'user.xdg.tags'
    attr_comment = 'user.xdg.comment'
    # Encoding to use when setting attribute values.
    encoding = sys.getdefaultencoding()
    # OSError number for no data available (attribute not available)
    errno_nodata = errno.ENODATA
    # Overridable separation character for tags when setting/parsing tags.
    tag_sep = ','
    # Whether xattr should follow symlinks.
    follow_symlinks = False

    class AttrError(EnvironmentError):
        """ Wrapper for EnvironmentError that is raised when getting, setting,
            or removing an attribute fails.
            Missing attributes, or empty attributes will not cause this.
        """
        pass

    def __init__(self, path):
        """ Resolves a file path and retrieves the tags and comment for it.
            Possibly raises FileNotFoundError, or ValueError (for empty path).
        """
        self.tags = []
        self.comment = ''
        try:
            self.path = self._get_path(path)
        except (FileNotFoundError, ValueError):
            raise
        else:
            # Only possible with a valid (resolved) path.
            self.filepath = str(self.path)
            self.tags = self.get_tags()
            self.comment = self.get_comment()

    def _get_path(self, path):
        """ Resolve and return `path` if given, otherwise return `self.path`.
            If neither are set, a ValueError is raised.
            Also possibly raises FileNotFoundError when resolving `path`.
        """
        if path:
            if isinstance(path, Path):
                self.path = path.resolve()
            elif isinstance(path, str):
                self.path = Path(path).resolve()
        if self.path:
            return self.path
        raise ValueError('No path set for this EditFile instance.')

    def add_tag(self, tag):
        """ Add a single tag to the tags for this file.
            Duplicate tags will not be added.
            Returns the new tags as a list.
            Raises ValueError if `tag` is falsey.
            Possibly raises AttrError.
        """
        if not tag:
            raise ValueError('Empty tags may not be added: {!r}'.format(tag))
        if tag in self.tags:
            return self.tags
        self.tags.append(tag)
        return self.set_tags(self.tags)

    def add_tags(self, taglist):
        """ Add multiple tags to this file.
            Duplicate tags will not be added.
            Returns the new tags as a list.
            Raises ValueError if taglist is empty.
            Possibly raises AttrError.
        """
        if not taglist:
            raise ValueError(
                'Empty tag list may not be added: {!r}'.format(taglist))
        self.tags.extend(taglist)
        return self.set_tags(self.tags)

    def clear_comment(self):
        """ Remove the entire comment attribute/value from this file.
            Returns True on success.
            Possibly raises AttrError.
        """
        return self.remove_attr(self.attr_comment)

    def clear_tags(self):
        """ Remove the entire tags attribute/value from this file.
            Returns True on success.
            Possibly raises AttrError.
        """
        return self.remove_attr(self.attr_tags)

    def get_attr(self, attrname):
        """ Retrieve a raw attribute value by name. """
        try:
            tagval = xattr.getxattr(
                self.filepath,
                attrname,
                symlink=self.follow_symlinks)
        except EnvironmentError as ex:
            if ex.errno == self.errno_nodata:
                # No data available.
                return None
            # Unexpected error.
            raise self.AttrError(
                'Unable to retrieve \'{}\' for: {}\n{}'.format(
                    attrname,
                    self.filepath,
                    ex))

        return tagval.decode()

    def get_attrs(self):
        """ Return a dict of {attr: value} for all extended attributes for
            this file.
            Possibly raises AttrError.
        """
        try:
            attrs = xattr.listxattr(
                self.filepath,
                symlink=self.follow_symlinks)
        except EnvironmentError as ex:
            if ex.errno == self.errno_nodata:
                return {}
            raise self.AttrError(
                'Unable to list attributes for file: {}'.format(self.filepath),
                ex)
        return {aname: self.get_attr(aname) for aname in attrs}

    def get_comment(self, refresh=False):
        """ Return the comment for this file.
            If self.comment is already set, return it.
            If `refresh` is truthy, or self.comment is not set, retrieve it.
        """
        if self.comment and (not refresh):
            # Comment was already retrieved, and we're not refreshing the data.
            return self.comment
        comment = self.get_attr(self.attr_comment)
        if not comment:
            return ''
        return comment.strip()

    def get_tags(self, refresh=False):
        """ Return sorted tags for this file.
            If self.tags is already set, return it.
            If `refresh` is truthy, or self.tags is not set, retrieve it.
        """
        if self.tags and (not refresh):
            # Tags were already retrieved, and we are not refreshing the tags.
            return self.tags

        tagstr = self.get_attr(self.attr_tags)
        return self.parse_tagstr(tagstr)

    def match_comment(self, repat, reverse=False, ignorecase=False):
        """ Return the comment if the regex pattern (`repat`) matches the
            comment.
            If `reverse` is used, returns the comment if the pattern does not
            match.
            Returns None on non-matches.
        """
        self.comment = self.get_comment()
        reflags = re.IGNORECASE if ignorecase else 0
        if reverse:
            matched = re.search(repat, self.comment, reflags) is None
        else:
            matched = re.search(repat, self.comment, reflags) is not None
        if matched:
            return self.comment
        return None

    def match_tags(self, repat, reverse=False, ignorecase=False):
        """ Return the tag list if the regex pattern (`repat`) matches any
            tags.
            If `reverse` is used, returns the tag list if none of the tags
            match.
            Returns None on non-matches.
        """
        self.tags = self.get_tags()
        reflags = re.IGNORECASE if ignorecase else 0
        if reverse:
            ismatch = lambda s: re.search(repat, s, reflags) is None
            # All tags must not match.
            boolfilter = all
        else:
            ismatch = lambda s: re.search(repat, s, reflags) is not None
            # Any tag may match.
            boolfilter = any
        if not self.tags:
            # Empty tags. Patterns will test against an empty string.
            return [] if ismatch('') else None

        if boolfilter(ismatch(s) for s in self.tags):
            return self.tags

        return None

    @classmethod
    def parse_taglist(cls, taglist):
        """ Parse a tag list into a attribute-friendly string.
            Sorts and removes duplicates.
        """
        return cls.tag_sep.join(sorted(set(taglist)))

    @classmethod
    def parse_tagstr(cls, tagstr):
        """ Parse a tag str into a sorted list.
            `tagstr` should be str or bytes.
        """
        if hasattr(tagstr, 'decode'):
            tagstr = tagstr.decode()
        if not tagstr:
            # Empty tag string.
            return []
        # It is possible that empty tags were set 'tag1,,tag2'...
        rawtags = (s.strip() for s in tagstr.split(cls.tag_sep))
        # Remove any empty tags.
        return sorted(s for s in rawtags if s)

    def remove_attr(self, attrname):
        """ Remove a raw attribute and value from this file.
            Returns True on success.
            Possibly raises AttrError.
        """
        try:
            xattr.removexattr(
                self.filepath,
                attrname,
                symlink=self.follow_symlinks)
        except EnvironmentError as ex:
            if ex.errno == self.errno_nodata:
                # Already removed.
                return True
            raise self.AttrError(
                'Unable to remove attribute \'{}\' for: {}\n{}'.format(
                    attrname,
                    self.filepath,
                    ex))
        return True

    def remove_comment(self):
        """ Remove the comment for this file.
            Returns True on success.
            Possibly raises AttrError.
            This is an alias for clear_comment().
        """
        return self.clear_comment()

    def remove_tag(self, tag):
        """ Remove a single tag from this file.
            Returns any tags that are left as a list.
            Does not care if the tag isn't present.
            Possibly raises AttrError.
        """
        try:
            self.tags.remove(tag)
        except ValueError:
            pass
        newtagstr = self.set_tags(self.tags)
        return self.parse_tagstr(newtagstr)

    def remove_tags(self, taglist):
        """ Remove multiple tags at once from this file.
            Returns any tags that are left as a list.
            Does not care if one of the tags isn't present.
            Possibly raises AttrError.
        """
        for t in taglist:
            try:
                self.tags.remove(t)
            except ValueError:
                pass
        newtagstr = self.set_tags(self.tags)
        return self.parse_tagstr(newtagstr)

    def set_attr(self, attrname, value):
        """ Set the value for a raw attribute.
            Value should be a string or bytes.
            Returns the value on success.
            Possibly raises AttrError.
        """
        if isinstance(value, bytes):
            encodedvalue = value
        elif isinstance(value, str):
            encodedvalue = value.encode(self.encoding)
        else:
            valtype = type(value)
            raise TypeError(
                'Expecting str or bytes. Got: {} ({})'.format(
                    getattr(valtype, '__name__', valtype),
                    value))
        try:
            xattr.setxattr(
                self.filepath,
                attrname,
                encodedvalue,
                symlink=self.follow_symlinks)
        except EnvironmentError as ex:
            raise self.AttrError(
                'Unable to set \'{}\' for: {}\n{}'.format(
                    attrname,
                    self.filepath,
                    ex))

        return value

    def set_comment(self, text):
        """ Set the comment for this file.
            Returns the comment on success.
            Possibly raises AttrError.
        """
        self.comment = self.set_attr(self.attr_comment, text)
        return self.comment

    def set_tags(self, taglist):
        """ Set the tags for this file.
            `taglist` should be an iterable of strings (tags).
            Removes any duplicate tags before setting.
            Returns the tags on success.
            Possibly raises AttrError.
        """
        tagstr = self.parse_taglist(taglist)
        newvalue = self.set_attr(self.attr_tags, tagstr)
        self.tags = self.parse_tagstr(newvalue)
        return self.tags


if __name__ == '__main__':
    ARGD = docopt(USAGESTR, version=VERSIONSTR)
    DEBUG = ARGD['--debug']
    QUIET = ARGD['--quiet']
    if ARGD['--nocolor']:
        # Override automatic detection.
        NOCOLOR = NOERRCOLOR = True

    try:
        MAINRET = main(ARGD)
    except KeyboardInterrupt:
        print_err('User cancelled.')
        MAINRET = 2
    except BrokenPipeError:
        print_err('Broken pipe, operation may have been interrupted.')
        MAINRET = 3
    sys.exit(MAINRET)
