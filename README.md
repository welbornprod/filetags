FileTags
========

Linux command to easily edit the extended attributes,
`user.xdg.tags` and `user.xdg.comment`, on files.
These are used by applications like [KDE]'s [Dolphin], [Baloo] and
others to tag files with keywords for searching/organizing later.

This tool can view, set, remove, clear, and search both tags and comments.
Tags and comments are encoded using the system's defaut encoding when saving.
Tags are also sorted and comma separated.

Output is colorized unless it is being piped or `--nocolor` is used.
The output can be silenced using `--quiet`, in case only the exit code matters.

Operates on all paths in the current directory unless file names are given.
The current directory can be recursed also.
Paths can be filtered (files only, or dirs only) whether they are user
provided or not.

Command Help
------------

```
Usage:
    filetags -h | -v
    filetags [-A | -c | -t] (FILE... | [-R]) [-l] [-D | -F] [-I | -q] [-N]
    filetags -a tag (FILE... | [-R])         [-l] [-D | -F] [-I | -q] [-N]
    filetags -d tag (FILE... | [-R])         [-l] [-D | -F] [-I | -q] [-N]
    filetags -m comment (FILE... | [-R])     [-l] [-D | -F] [-I | -q] [-N]
    filetags -C [-c] (FILE... | [-R])        [-l] [-D | -F] [-I | -q] [-N]
    filetags -s pat [-c] [-n] [-r] [-R]      [-l] [-D | -F] [-I | -q] [-N]
    filetags -s pat [-c]  FILE... [-n] [-r]  [-l] [-D | -F] [-I | -q] [-N]

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
```

Requirements
------------

* **Python 3.4+** - Uses `yield from` and other 3+ features.

Python libraries (installed using [pip](https://pip.pypa.io/en/latest/installing/)):

* **colr** - Provides colorized terminal output for linux.
* **docopt** - Parses command line arguments.
* **xattr** - Allows editing extended attributes on files.

A `requirements.txt` file is provided, so this one command will install all of
the required python libraries:

```
pip3 install -r requirements.txt
```

...where `pip3` may have another name on your system (`pip-3.4`, `pip`, etc.).

Installation
------------

Download the `filetags.py` script, ensure all [requirements](#requirements) are
installed, and symlink it to a directory in `$PATH`:

```
cd path_to_filetags
chmod +x filetags.py
ln -s "$PWD/filetags.py" ~/.local/bin/filetags
```

Examples
--------

###Viewing
Viewing and editing commands can be used on one or more files.

####View file tags:

```
$ filetags *.py
/home/me/scripts/filetags.py:
    python
    script
```

This is the same as `filetags -t *.py`.

####View file comment:

```
$ filetags -c *.py
/home/me/scripts/filetags.py:
    Edit one or more file tags and comments.
```

####View all extended attributes:

```
$ filetags -A *.py
/home/me/scripts/filetags.py:
    user.xdg.comment: Editor for file tags and comments.
       user.xdg.tags: python,script,test
```

###Editing

####Add a tag to a file:

```
$ filetags -a test *.py
Set tags for /home/me/scripts/filetags.py:
    python
    script
    test
```

####Add two tags to a file:

```
$ filetags -a 'python,script' filetags.py
Set tags for /home/me/scripts/filetags.py:
    python
    script
```
...no duplicate tags are ever added.

####Remove a tag from a file:

```
$ filetags -d test filetags.py
Set tags for /home/me/scripts/filetags.py:
    python
    script
```
...notice the `test` tag is now missing.

You can also remove several tags at once by using commas to separate them:

```
$ filetags -d 'test,this'
```

####Clear all tags for a file:

```
$ filetags -C filetags.py
Cleared tags for /home/me/scripts/filetags.py
```

You can add a `-c` to clear comments.

####Change the comment for a file:

```
$ filetags -m 'Editor for file tags and comments.' *.py
Set comment for /home/me/scripts/filetags.py:
    Editor for file tags and comments.
```

###Searching

Search uses a regex or text pattern to match against. Tags and comments can
be searched, with options to print only file names and exclude colors. If
`--reverse` is used, non-matching tags/comments will be reported.

Search will accept file name arguments, but the default action is to search
all files in the current directory. When `-R` (`--recurse`) is used, all sub
directories and files are walked to check for matches.

####Search file tags:

```
$ filetags -s python
/home/me/scripts/mything.py:
    python
    script
    things
/home/me/scripts/other.py:
    python
    script
    other

Found 2 tags.
```

####Search comments:

```
$ filetags -c -s '(things)|(stuff)'
/home/me/scripts/mydirectory:
    My directory for holding things.
/home/me/scripts/mythings.py:
    A script that does stuff.

Found 2 comments.
```

You can also search directories only with `--dirs`,
or files only with `--files`.

Between the `filetags` command and BASH features, you can pretty much do
anything you would want to do with file tags. For example, to list all files
with 'test' in their name that are not tagged with 'test':

```bash
$ find -name "*test*" -exec filetags -s test -r -n "{}" +
```

...where `-n` means 'print names only', and `-r` means 'reverse search'.

Or if you don't care about the output, you can check the exit code:

```bash
if filetags -s py -q; then
    echo "Some file in this directory has a tag containing 'py'."
else
    echo "No py tag here."
fi
```

...where `-q` will silence all output to stdout.


Notes
-----

This project is built upon the [xattr] module by Bob Ippolito, and would not
exist without it. I did not include options for editing raw attributes because
[xattr] already comes with a command by the same name to do exactly that.


[xattr]: https://github.com/xattr/xattr
[Baloo]: https://community.kde.org/Baloo
[Dolphin]: https://www.kde.org/applications/system/dolphin/
[KDE]: https://www.kde.org
