.. contents::

Introduction
============

This package provides a command-line control for export of RCR journal articles
to the JATS format, suitable for indexing by PubMed Central.


Usage
=====
rcrexport [-h] [-p /path/to/php] [-o /path/to/output] /path/to/rcr ID [ID ...]

Produce an output zip file for each supplied article id

Positional Arguments
--------------------

/path/to/rcr
    Full path to the directory where RCR is installed

ID
    Published article ID(s) separated by spaces

Optional Arguments
------------------

-h, --help
    show this help message and exit

-p /path/to/php, --php /path/to/php
    Specific php executable to be used (defaults to first found in path)

-o /path/to/output, --output /path/to/output
    Specify a directory in which to write output (defaults to current working 
    directory)


Caveats
-------

The processing of cross-references in article text to figures and bibliography
is dependent upon the certain formatting standards for in-line references.

For bibliography, references to items in the article references list should
take the form "(N[, N[, N[...]]])" where each 'N' is the number of a specific
reference listed in the article references list.  There may be more than one
reference cited in each parenthetical, but each should be separated by a comma
and the entire form must be enclosed in parentheses.  

For figures, inline references should be enclosed in parentheses and the first
element of the reference should be one of the words "Fig." or "Figs.". If
there will be more than one figure referenced in the statement, each should be
separated by a comma. Series notation like "(Figs. 1-3)" **is not allowed**.
If the multiple references are to sub-figures (like 1A, 1B, 1C) then the
alphabetical portion of the reference may be listed in series: "(Figs 1A-C)".
Use the following guidelines to help determine the right way to go:

**Good**:

* (Fig. 1)
* (Fig. 1A)
* (Figs. 2, 3)
* (Figs. 1A-C)

**Bad**:

* (Figs 1-3) [use (Figs. 1, 2, 3) instead]

