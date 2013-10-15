# -*- coding: utf-8 -*-

from argparse import ArgumentParser
from rcr_export_control.utils import bin_search
from subprocess import Popen
from subprocess import PIPE
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


def execute_php_export(command, articleid):
    print "PHP Exporting article {0}:\n\t`$ {1}\n`".format(articleid, command)
    args = command.split()
    process = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    pout, perr = process.communicate()
    code = process.poll()
    if code or pout or perr:
        output = pout + perr
        try:
            raise CalledProcessError(
                code, command, output=output
            )
        except Exception, e:
            import pdb; pdb.set_trace( )
            error = CalledProcessError(code, command)
            error.output = output
            raise error
    print "PHP export of article {0} complete\n".format(articleid)
    return code


def main():
    arguments = parser.parse_args()
    import pdb; pdb.set_trace( )

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
        except CalledProcessError:
            print "Export of {0} failed due to previous errors\n".format(
                articleid
            )
            sys.exit(1)
            return

        # read exported xml to build zip archive for this article
        with open(tmp_xml_path, 'r') as fh:
            exported = fh.read()

        # cleanup
        # os.unlink(tmp_xml_path)


if __name__ == '__main__':
    main()
