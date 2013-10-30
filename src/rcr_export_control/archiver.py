# -*- coding: utf-8 -*-
from bs4 import element
from copy import deepcopy
from lxml import etree
from rcr_export_control.xml_tools import convert_tag_type
from rcr_export_control.xml_tools import extract_reference_pmids
from rcr_export_control.xml_tools import get_archive_id
from rcr_export_control.xml_tools import get_archive_content_base_id
from rcr_export_control.xml_tools import parse_article_html
from rcr_export_control.xml_tools import set_sec_type
from rcr_export_control.xml_tools import set_namespaced_attribute

import os
import requests
import zipfile


HOME = os.path.dirname(__file__)


class JATSArchiver(object):
    """handles converting PHP exported JATS to PMC compliant zip archive"""
    
    parsed_xml = None
    out_path = None
    reference_tree = None
    converted = False
    figure_list = []
    galley_files = []
    supplemental_files = []
    compression = zipfile.ZIP_STORED
    pubmed_base_url = "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    base_query = {
        'db': 'pubmed',
        'version': '2.0',
    }


    def __init__(self, parsed, out_path):
        self.parsed_xml = parsed
        self.out_path = out_path
        try:
            import zlib
            self.compression = zipfile.ZIP_DEFLATED
        except:
            pass

    @property
    def raw(self):
        if not hasattr(self, '_raw'):
            keys = ('markup', 'galleys', 'supplemental_files')
            self._raw = dict(zip(keys, self._exerpt_body_content()))
        return self._raw


    @property
    def cooked(self):
        return (self.galley_files, self.supplemental_files)

    @property
    def transform(self):
        if not hasattr(self, '_transform'):
            transform_path = os.path.join(HOME, 'pubmed_jats_transform.xsl')
            with open(transform_path) as fh:
                self._transform = etree.XSLT(etree.XML(fh.read()))
        return self._transform

    # Public API

    def convert(self):
        """iteratively build body sections"""
        body = self.parsed_xml.find('body')
        if 'markup' in self.raw:
            if self.raw['markup'] is None:
                raise ValueError('exported xml has no page markup')
            html = parse_article_html(self.raw['markup'])
            ref_ids = extract_reference_pmids(html)
            self._handle_references(ref_ids)

            header_tags = html.find_all('p', class_='subheading')
            # XXX this should be logging to an output stream
            print "building {0} sections".format(len(header_tags))

            for header_tag in header_tags:
                heading = header_tag.text
                sec_node = None
                if heading not in ['Abstract', 'References']:
                    # XXX this should be logging to an output stream
                    print "building section from {0}\n\n".format(header_tag)
                    # dump abstract, it's elsewhere
                    # handle references separately
                    sec_node = etree.SubElement(body, 'sec')
                    sec_node.tail = "\n"
                    set_sec_type(sec_node, heading)
                    sec_title = etree.SubElement(sec_node, 'title')
                    sec_title.tail = "\n"
                    sec_title.text = heading
                    self._build_section(sec_node, header_tag)

            self._append_back_matter()

        self.converted = True


    def archive(self):
        """write the results of conversion out to a zip file archive"""
        if not self.converted:
            raise RuntimeError('must call archiver.convert() before archiving')
        base_filename = get_archive_id(self.parsed_xml)
        inner_basename = get_archive_content_base_id(base_filename)
        archive_name = base_filename + '.zip'
        archive_path = os.path.join(self.out_path, archive_name)
        archive = zipfile.ZipFile(
            archive_path, 'w', compression=self.compression
        )
        xml_filename = inner_basename + '.xml'
        archive.writestr(
            xml_filename, etree.tostring(
                self.parsed_xml,
                encoding='utf-8',
                xml_declaration=True,
                pretty_print=True
            )
        )
        archive.close()

    # Private API

    def _exerpt_body_content(self):
        """remove child nodes of the exported XML body tag for processing"""
        root = self.parsed_xml.getroot()
        body = root.find('body')
        results = []
        for lookfor in ['article-markup', 'galley-files', 'supplemental-files']:
            node = body.find(lookfor)
            if node is not None:
                body.remove(node)
            results.append(node)
        return results


    def _build_section(self, sec_node, header_tag):
        """walk the siblings after the section heading and insert p's"""
        for tag in header_tag.next_siblings:
            if isinstance(tag, element.Tag):
                print "investigating tag: {0}\n\n".format(tag)
                if 'class' in tag.attrs:
                    comp = map(str.lower, tag['class'])
                    if 'subheading' in comp:
                        # stop when we reach the next subheading
                        print "breaking loop on new subheading: {0}\n\n".format(tag)
                        break
                    elif 'figure' in comp:
                        # this is a figure.  Deal with it.
                        f_node = etree.SubElement(sec_node, 'fig')
                        self._process_figure(f_node, tag)
                else:
                    if tag.name == 'p':
                        # if the article has yet to be converted to using the
                        # 'figure' class on figure paragraphs, try to catch
                        # figures anyway.
                        if tag.find('span', class_="figureCaption") is not None:
                            # this is a figure.  Deal with it.
                            f_node = etree.SubElement(sec_node, 'fig')
                            self._process_figure(f_node, tag)
                            
                        print 'adding paragraph {0} to section\n\n'.format(tag)
                        # import pdb; pdb.set_trace( )
                        p_node = etree.SubElement(sec_node, 'p')
                        self._process_paragraph(p_node, tag)
                        p_node.tail = "\n"

            elif isinstance(tag, element.NavigableString):
                # XXX Log navigable strings with non-whitespace in case we're
                #     missing something important
                pass


    def _process_paragraph(self, p_node, p_tag):
        """iteratively process the children of an HTML paragraph tag"""
        tailable = None

        for tag in p_tag.children:
            if isinstance(tag, element.NavigableString):
                insert = unicode(tag.string)
                # XXX: process inline references to bibliography and 
                #      figures here?
                if tailable is None:
                    p_node.text = insert
                else:
                    tailable.tail = insert
                    tailable = None
            elif isinstance(tag, element.Tag):
                if tag.name.lower() == 'a':
                    tailable = self._process_link(p_node, tag)
                else:
                    tailable = self._insert_tag(p_node, tag)

    def _process_figure(self, f_node, f_tag):
        self.figure_list.append(f_node)
        self._set_figure_id(f_node)
        for caption_tag in f_tag.find_all('span', class_='figureCaption'):
            caption_tag.name = 'p'
            caption_node = etree.SubElement(f_node, 'caption')
            caption_p = etree.SubElement(caption_node, 'p')
            self._process_paragraph(caption_p, caption_tag)
            caption_node.tail = "\n"
        for img_tag in f_tag.find_all('img'):
            graphic_node = self._insert_tag(f_node, img_tag)
            set_namespaced_attribute(
                graphic_node, 'href', img_tag['src'], prefix='xlink'
            )
            graphic_node.tail = "\n"
        f_node.tail = "\n"


    def _insert_tag(self, node, tag):
        """insert a subnode based on node"""
        subnode_type = convert_tag_type(tag)
        subnode = etree.SubElement(node, subnode_type)
        subnode.tail = "\n"
        tailable = None

        for child in tag.children:
            if isinstance(child, element.NavigableString):
                insert = unicode(child.string)
                # XXX: process inline references to bibliography and 
                #      figures here?
                if tailable is None:
                    subnode.text = insert
                else:
                    tailable.tail = insert
                    tailable = None
            elif isinstance(child, element.Tag):
                tailable = self._insert_tag(subnode, child)

        return subnode


    def _process_link(self, node, tag):
        """convert html links into cross-reference tags for JATS"""
        # XXX: Fix This to do the right thing
        return self._insert_tag(node, tag)


    def _handle_references(self, ids):
        """build reference tree from a list of pubmed ids

        The tree is built by querying the PubMed esummary eutil for docsummary
        xml. This is then transformed through xslt into a JATS-compliant ref-list
        element and that element is returned.
        """
        print "Looking up {0} references".format(len(ids))
        query = {'id': ','.join(ids)}
        query.update(self.base_query)
        resp = requests.get(self.pubmed_base_url, params=query)
        if resp.ok:
            # must pass a byte-string to the parser
            source = etree.XML(resp.content)
            self.reference_tree = self.transform(source)
            print "References parsed"
        else:
            print "Reference Lookup Failed"
            raise IOError

    def _append_back_matter(self):
        if self.reference_tree is not None:
            back = etree.SubElement(self.parsed_xml.getroot(), 'back')
            ref_list = deepcopy(self.reference_tree).getroot()
            back.append(ref_list)

    def _set_figure_id(self, f_node):
        tmpl = 'fig-{0}'
        f_node.attrib['id'] = tmpl.format(self.figure_list.index(f_node) + 1)
