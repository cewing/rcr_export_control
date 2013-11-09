# -*- coding: utf-8 -*-
from rcr_export_control import constants
from rcr_export_control.archiver import JATSArchiver
from rcr_export_control.xml_tools import parse_export_xml
from subprocess import Popen
from subprocess import PIPE
from subprocess import CalledProcessError

import mimetypes
import os
import sys


class MissingBinary(Exception): 
    pass


_marker = object()


def bin_search(binary, default=_marker):
    """ Search the bin_search_path for a given binary

        Returns its fullname or raises MissingBinary exception

        We assume we have a python(.exe) installed anywhere in
        the path. This seems one of the safest test.
        >>> from bibliograph.core.utils import bin_search
        >>> bin_search('python') != ''
        True

        >>> bin_search('a_completely_stupid_command')
        Traceback (most recent call last):
        ...
        MissingBinary: Unable to find binary "a_completely_stupid_command" ...

        >>> bin_search('a_completely_stupid_command', '/bin/default')
        '/bin/default'

        Let's see if the additional path is searched.
        First we create a temporary directory and add it to the
        environment.
        >>> import os, stat, tempfile
        >>> dir = tempfile.mkdtemp()
        >>> os.environ['PHP_PATH'] = dir

        Now create a dummy executable we want to find.
        >>> exe = os.path.join(dir, '_stub_testing_file')
        >>> f = open(exe, 'w')
        >>> f.write('foobar')
        >>> f.close()
        >>> os.chmod(exe, stat.S_IXUSR | stat.S_IRUSR)

        Do the search and compare.
        >>> bin_search('_stub_testing_file') == exe
        True

        Cleanup.
        >>> os.unlink(exe)
        >>> os.rmdir(dir)
    """
    mode   = os.R_OK | os.X_OK
    envPath = os.environ['PATH']
    customPath = os.environ.get('PHP_PATH', '')
    searchPath = os.pathsep.join([customPath, envPath])
    bin_search_path = [path for path in searchPath.split(os.pathsep)
                       if os.path.isdir(path)]

    if sys.platform == 'win32':
        extensions = ('.exe', '.com', '.bat', )
    else:
        extensions = ()

    for path in bin_search_path:
        for ext in ('', ) + extensions:
            pathbin = os.path.join(path, binary) + ext
            if os.access(pathbin, mode) == 1:
                return pathbin

    if default is _marker:
        raise MissingBinary('Unable to find binary "%s" in %s w' %
                           (binary, os.pathsep.join(bin_search_path)))
    else:
        return default


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
        except Exception:
            error = CalledProcessError(code, command)
            error.output = output
            raise error
    print "PHP export of article {0} complete\n".format(articleid)
    return code


def create_article_archive(out_path, exported, log_level=0):
    parsed = parse_export_xml(exported)
    archiver = JATSArchiver(parsed, out_path, log_level)
    archiver.convert()
    archiver.archive()
    
    # clean up memory space:
    del archiver
