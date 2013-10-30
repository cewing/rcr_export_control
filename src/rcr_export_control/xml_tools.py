# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
from bs4 import element
from lxml import etree
from rcr_export_control import constants
from urlparse import urlparse
from urlparse import parse_qs

def parse_export_xml(exported):
    """parse the xml exported by the PHP JATS exporter plugin"""
    parser = etree.XMLParser(encoding='utf-8')
    parsed = etree.parse(exported, parser)
    return parsed


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


def convert_galley(galley_node):
    galley = {'id': galley_node.attrib['galley-id']}
    if 'html' in galley_node.tag.lower():
        galley['type'] = 'html'
    else:
        galley['type'] = galley_node.find('label').text.lower()

    files = []
    for node in galley_node.findall('file'):
        files.append(filenode_to_dict(node))
    if files:
        galley['files'] = files

    images = []
    for node in galley_node.findall('image'):
        images.append(filenode_to_dict(node))
    if images:
        galley['images'] = images

    return galley


def convert_galleys(gal_node):
    galleys = []
    if gal_node is not None:
        for galley in gal_node:
            galleys.append(convert_galley(galley))
    return galleys


def convert_supplemental_files(supp_node):
    files = []
    if supp_node is not None:
        for node in supp_node:
            files.append(filenode_to_dict(node))
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
    ref_graph = html.find('p', class_='references')
    # this is our references paragraph, use it
    links = ref_graph.find_all('a')
    for link in links:
        url = link.get('href')
        if url is not None:
            query = urlparse(url).query
            if query:
                qdict = parse_qs(query)
                if 'list_uids' in qdict:
                    pmids.extend(qdict['list_uids'])
    return pmids


def set_namespaced_attribute(node, a_name, a_value, prefix=None):
    try:
        ns = '{{{0}}}'.format(constants.JATS_NSMAP[prefix])
    except KeyError:
        ns = ''
    tmpl = '{ns}{name}'
    node.attrib[tmpl.format(ns=ns, name=a_name)] = a_value
