# -*- coding: utf-8 -*-
from lxml import etree


def parse_export_xml(exported):
    parser = etree.XMLParser(encoding='utf-8')
    parsed = etree.parse(exported, parser)
    return parsed


def get_base_file_id(parsed):
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


def convert_file_id_to_article_id(file_id):
    parts = file_id.split('-')
    return "{0}-{1}-{3}".format(*parts)


def exerpt_body_content(parsed):
    root = parsed.getroot()
    body = root.find('body')
    results = []
    for lookfor in ['article-markup', 'galley-files', 'supplemental-files']:
        node = body.find(lookfor)
        if node is not None:
            body.remove(node)
        results.append(node)
    return results


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
    for galley in gal_node:
        galleys.append(convert_galley(galley))
    return galleys


def convert_supplemental_files(supp_node):
    files = []
    for node in supp_node:
        files.append(filenode_to_dict(node))
    return files
