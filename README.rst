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