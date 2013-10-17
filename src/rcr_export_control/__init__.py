# -*- coding: utf-8 -*-
from argparse import ArgumentParser
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
TOOL = 'tools/importExport.php'
EXPORTER = 'JATSImportExportPlugin'
COMMAND_LINE = "{exe} {tool} {exporter} export {tempout} rcr article {id}"


parser = ArgumentParser(description=DESCRIPTION)
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
            create_article_archive(output_path, fh)

        # cleanup
        os.unlink(tmp_xml_path)


if __name__ == '__main__':
    main()
