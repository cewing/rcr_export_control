# -*- coding: utf-8 -*-
from lxml import etree
from rcr_export_control.xml_tools import parse_export_xml
from rcr_export_control.xml_tools import exerpt_body_content
from rcr_export_control.xml_tools import get_base_file_id
from rcr_export_control.xml_tools import convert_file_id_to_article_id
from rcr_export_control.xml_tools import convert_galleys
from rcr_export_control.xml_tools import convert_supplemental_files
from subprocess import Popen
from subprocess import PIPE
from subprocess import CalledProcessError

import os
import sys
import zipfile

try:
    import zlib
    compression = zipfile.ZIP_DEFLATED
except:
    compression = zipfile.ZIP_STORED


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


def create_article_archive(out_path, exported):
    import pdb; pdb.set_trace( )
    parsed = parse_export_xml(exported)
    base_filename = get_base_file_id(parsed)
    inner_basename = convert_file_id_to_article_id(base_filename)
    markup_node, galleys_node, supplemental_node = exerpt_body_content(parsed)
    galleys = []
    supp_files = []
    if galleys_node is not None:
        galleys = convert_galleys(galleys_node)
    if supplemental_node is not None:
        supp_files = convert_supplemental_files(supplemental_node)
    archive_name = base_filename + '.zip'
    archive_path = os.path.join(out_path, archive_name)
    archive = zipfile.ZipFile(archive_path, 'w', compression=compression)
    xml_filename = inner_basename + '.xml'
    archive.writestr(
        xml_filename, etree.tostring(
            parsed, encoding='utf-8', xml_declaration=True
        )
    )
    archive.close()
