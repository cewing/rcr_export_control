# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
from bs4 import element
from cStringIO import StringIO
from lxml import etree
from rcr_export_control import constants
from urlparse import urlparse
from urlparse import parse_qs

import mimetypes
import os
import re


XML_ILLEGALS = u'|'.join(u'[%s-%s]' % (s, e) for s, e in [
    (u'\u0000', u'\u0008'),             # null and C0 controls
    (u'\u000B', u'\u000C'),             # vertical tab and form feed
    (u'\u000E', u'\u001F'),             # shift out / shift in
    (u'\u007F', u'\u009F'),             # C1 controls
    (u'\uD800', u'\uDFFF'),             # High and Low surrogate areas
    (u'\uFDD0', u'\uFDDF'),             # not permitted for interchange
    (u'\uFFFE', u'\uFFFF'),             # byte order marks
    ])
RE_SANITIZE_XML = re.compile(XML_ILLEGALS, re.M | re.U)
REF_PAT = re.compile('(\d{1,3})\.')


def parse_export_xml(exported):
    """parse the xml exported by the PHP JATS exporter plugin"""
    parser = etree.XMLParser(encoding='utf-8')
    fixed = StringIO(remove_illegal_chars(exported))
    parsed = etree.parse(fixed, parser)
    return parsed


def remove_illegal_chars(exported):
    """remove illegal characters for XML from the source exported from PHP"""
    decoded_source = exported.read().decode('utf-8')
    sanitized = RE_SANITIZE_XML.sub('', decoded_source)
    return sanitized.encode('utf-8')


def parse_article_html(html_node):
    """parse the html contained in an article node

    use beautiful soup because it will try to normalize the messy html we
    are likely to see.
    """
    if html_node is None:
        return

    parsed = BeautifulSoup(html_node.text)
    return parsed


def get_archive_id(parsed):
    """construct a base identifier string for article and files

    id is in the format jour-vol-articleid
    """
    ids = {'jour': 'rcr', 'vol': None, 'iss': None, 'aid': None}
    
    meta = parsed.find('.//article-meta')
    if meta is not None:
        ids['vol'] = meta.find('volume').text
        ids['iss'] = meta.find('issue').text
        for node in meta.findall('article-id'):
            if node.attrib['pub-id-type'] == 'doi':
                ids['aid'] = node.text.rsplit('.', 1)[1]
    if None not in ids:
        return "{jour}-{vol}-{iss}-{aid}".format(**ids)


def get_archive_content_base_id(file_id):
    """article xml and internal ids have a different base id format than archives"""
    parts = file_id.split('-')
    return "{0}-{1}-{3}".format(*parts)


def filenode_to_dict(node):
    node_dict = dict(node.items())
    special = {'name': node.tag, 'path': node.text}
    node_dict.update(special)
    return node_dict


def store_item_by_key(storage, item, key):
    holder = storage.setdefault(item[key], [])
    holder.append(item)


def convert_galley(galley_node):
    galley = {'id': galley_node.attrib['galley-id']}
    if 'html' in galley_node.tag.lower():
        galley['type'] = 'html'
    else:
        galley['type'] = galley_node.find('label').text.lower()

    files = {}
    for node in galley_node.findall('file'):
        converted = filenode_to_dict(node)
        store_item_by_key(files, converted, 'filename')
    if files:
        galley['files'] = files

    images = {}
    for node in galley_node.findall('image'):
        converted = filenode_to_dict(node)
        store_item_by_key(images, converted, 'filename')
    if images:
        galley['images'] = images

    return galley


def convert_galleys(gal_node):
    galleys = {}
    if gal_node is not None:
        for galley in gal_node:
            converted = convert_galley(galley)
            store_item_by_key(galleys, converted, 'type')
    return galleys


def convert_supplemental_files(supp_node):
    files = {}
    if supp_node is not None:
        for node in supp_node:
            converted = filenode_to_dict(node)
            store_item_by_key(files, converted, 'filename')
    return files


def set_sec_type(sec, heading):
    """set the 'sec_type' attribute of 'sec', if applicable"""
    comp = heading.lower()
    sec_type = None
    if comp in constants.JATS_SEC_TYPES:
        sec_type = comp
    if comp in constants.RCR_TO_JATS_SEC_MAPPING:
        sec_type = constants.RCR_TO_JATS_SEC_MAPPING[comp]

    if sec_type:
        sec.set('sec-type', sec_type)


def convert_tag_type(tag):
    """convert html tag types to JATS xml compliant tag types"""
    if tag.name in constants.HTML_TO_JATS_MAPPING:
        return constants.HTML_TO_JATS_MAPPING[tag.name]
    else:
        return tag.name


def extract_reference_pmids(html):
    """given a reference header, find the reference paragraph and get pmids
    
    HTML input should look something like this:
    <p class="subheading">References</p> <-- this is the incoming tag
    <p class="references">
    1. Barrett NR. Report of a case of spontaneous perforation of the oesophagus successfully treated by operation.
    <em>
     Br J Surg
    </em>
    . 1947 Oct;35(138):216-8. [
    <a href="http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&amp;db=pubmed&amp;dopt=Abstract&amp;list_uids=20271775&amp;query_hl=9&amp;itool=pubmed_docsum" target="_blank">
     PubMed
    </a>
    ]
    <br/>
    <br/>
    2. de Schipper JP, Pull ter Gunne AF, Oostvogel HJM, van Laarhoven CJHM. Spontaneous rupture of the oesophagus: Boerhaave’s syndrome in 2008.
    <em>
     Dig Surg
    </em>
    2009;26:1-6. [
    <a href="http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&amp;db=pubmed&amp;dopt=Abstract&amp;list_uids=19145081&amp;query_hl=9&amp;itool=pubmed_docsum" target="_blank">
     PubMed
    </a>
    ]
    <br/>
    <br/>
    """
    pmids = []
    pmid_candidate = [None]
    seeking_pmid = False
    ref_graphs = html.find_all('p', class_='references')
    # iterate over each reference paragraph:
    for ref_graph in ref_graphs:
        # iterate over immediate child nodes in the paragraph
        for node in ref_graph.children:
            # look for navigable strings (these might be our references)
            if isinstance(node, element.NavigableString):
                # check to see if the current navigable string starts with
                # an integer (this is definitely a reference)
                match = REF_PAT.match(node.strip())
                if match is not None:
                    # new_pmid_count = int(match.groups()[0])
                    # # have we reached a new reference?
                    # if new_pmid_count > current_pmid_count:
                    if seeking_pmid:
                        pmids.extend(pmid_candidate)
                        pmid_candidate = [None]
                    else:
                        seeking_pmid = True
                    # current_pmid_count = new_pmid_count
            elif isinstance(node, element.Tag) and node.name == ('a'):
                url = node.get('href')
                if url is not None:
                    query = urlparse(url).query
                    if query:
                        qdict = parse_qs(query)
                        if 'list_uids' in qdict:
                            pmid_candidate = qdict['list_uids']
    # at the end of it all, we append whatever pmid_candidate we have
    pmids.extend(pmid_candidate)
    return pmids


def set_namespaced_attribute(node, a_name, a_value, prefix=None):
    try:
        ns = '{{{0}}}'.format(constants.JATS_NSMAP[prefix])
    except KeyError:
        ns = ''
    tmpl = '{ns}{name}'
    node.attrib[tmpl.format(ns=ns, name=a_name)] = a_value


def get_namespaced_attribute(node, a_name, prefix=None, default=None):
    try:
        ns = '{{{0}}}'.format(constants.JATS_NSMAP[prefix])
    except KeyError:
        ns = ''
    key = '{ns}{name}'.format(ns=ns, name=a_name)
    return node.attrib.get(key, default)
    


def is_internal(href):
    """determine if an href is internal to RCR"""
    # if an absolute local link, or relative local link
    if href.startswith('/') or not href.startswith('http'):
        return True

    # if an RCR domain is in the link
    for domain in constants.RCR_DOMAINS:
        if domain in href:
            return True

    return False


def is_media_url(href):
    mime = mimetypes.guess_type(os.path.basename(href))
    if mime[0] is None:
        # in rcr, this is urls like 
        # http://radiology.casereports.net/index.php/rcr/article/view/433/1117
        return False

    prefix = mime[0].split('/')[0]
    if prefix in constants.MEDIA_MIME_TYPE_PREFIXES:
        return True

    return False


def get_index_from_figure_ref(ref):
    """return indexes from integer parts of figure references like '1' or '2a'
    
    >>> get_index_from_figure_ref('1')
    0
    >>> get_index_from_figure_ref('2a')
    1
    """
    dig_pat = re.compile('[\d]{1,3}')
    match = dig_pat.search(ref)
    if match is None:
        return None

    return int(ref[match.start():match.end()]) - 1


class DateParserXSLTExtension(etree.XSLTExtension):
    """helper class for parsing sloppy dates incoming from pubmed"""

    def execute(self, context, self_node, input_node, output_parent):
        """some notes on what this does and how"""
        date_input = input_node.text
        date_parts = date_input.split(' ')
        year_node = etree.Element('year')
        year_node.text = date_parts[0]
        output_parent.append(year_node)
        if len(date_parts) > 1:
            # the second part is always the month, if present
            month_node = etree.Element('month')
            month_node.text = date_parts[1]
            output_parent.append(month_node)
            if len(date_parts) > 2:
                # the third part is the day
                day_node = etree.Element('day')
                day_node.text = date_parts[2]
                output_parent.append(day_node)
