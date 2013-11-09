# -*- coding: utf-8 -*-
from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter
from rcr_export_control.utils import bin_search
from rcr_export_control.utils import execute_php_export
from rcr_export_control.utils import create_article_archive
from subprocess import CalledProcessError

import os
import sys
import tempfile


DESCRIPTION = """
Produce an output zip file for each supplied article id
"""
EPILOG = """
`rcrexport` creates zip archives of the required materials needed to submit an
article from Radiology Case Reports for submission to PubMedCentral for 
indexing.  It does so by exporting the article via PHP, and then transforming
the result in a Python process.

NARRATIVE DOCUMENTATION

First, you must find the ID of the article or articles you wish to export. You
can use the URL for a published article to obtain the required ID.  For 
example, view the article at the following URL:

    http://radiology.casereports.net/index.php/rcr/article/view/793

The ID of the article is the integer value at the end of that URL, '793'.  To
export this article, use that id in the command, like so:

    $ rcrexport /path/to/rcr/home 793

This will export the article from the journal, creating a zip archive in the
current directory.  To change the destination of the zip file, use the '-o' 
command-line flag, followed by a path leading to the directory where you'd
like the result to be written:

    $ rcrexport /path/to/rcr/home 793 -o /path/to/somewhere/else

By default, the command-line output of this script is extremely verbose.  This
is designed to assist the user in spotting problems with the rendering of 
article HTML before sending the article off for indexing.  One way to handle
this output is to redirect it into a report textfile:

    $ rcrexport /path/to/rcr/home 793 > 793_export_report.txt

In this way, the output from the script can be reviewed line-by-line to ensure
that the results are correct.  

In addition, it is possible to reduce the verbosity of the output to a minimal
level.  Critical errors will always be output, but by using the '-q' flag, 
less important output can be removed. Increasing the number of 'q' flags will
further reduce output:

    $ rcrexport /path/to/rcr/home 793 -qqq

Any increase in the number of 'q' flags beyond 3 will be ignored.
"""
TOOL = 'tools/importExport.php'
EXPORTER = 'JATSImportExportPlugin'
COMMAND_LINE = "{exe} {tool} {exporter} export {tempout} rcr article {id}"


parser = ArgumentParser(
    description=DESCRIPTION,
    epilog=EPILOG,
    formatter_class=RawDescriptionHelpFormatter)
parser.add_argument(
    'rcr_path',
    metavar="/path/to/rcr",
    help="Full path to the directory where RCR is installed",
)
parser.add_argument(
    'articleids', 
    metavar="ID", 
    type=int, 
    nargs='+', 
    help='Published article ID(s) separated by spaces',
)
parser.add_argument(
    '-p', 
    '--php', 
    metavar="/path/to/php",
    help="Specific php executable to be used (defaults to first found in path)",
)
parser.add_argument(
    '-o',
    '--output',
    metavar="/path/to/output",
    help="Specify a directory in which to write output (defaults to current"
         " working directory)",
)
parser.add_argument(
    '-q',
    '--quiet',
    action='count',
    help="Decrease the verbosity of script output"
)


def main():
    arguments = parser.parse_args()

    # default to first found on path
    executable = arguments.php
    if not executable:
        executable = bin_search('php')

    # default to current working directory
    output_path = arguments.output
    if not output_path:
        output_path = os.getcwd()

    rcr_path = arguments.rcr_path

    for articleid in arguments.articleids:
        tmp_xml_fh, tmp_xml_path = tempfile.mkstemp(suffix=".xml")
        cl = COMMAND_LINE.format(**{
            'exe': executable,
            'tool': os.path.join(rcr_path, TOOL),
            'exporter': EXPORTER,
            'tempout': tmp_xml_path,
            'id': articleid,
        })

        # export article via command-line exporter
        try:
            execute_php_export(cl, articleid)
        except CalledProcessError, e:
            print "Export of {0} failed due to previous errors: {1}\n".format(
                articleid, e.output
            )
            sys.exit(1)
            return

        # read exported xml to build zip archive for this article
        with open(tmp_xml_path, 'r') as fh:
            log_level = arguments.quiet
            create_article_archive(output_path, fh, log_level=log_level)

        # cleanup
        os.unlink(tmp_xml_path)


if __name__ == '__main__':
    main()
