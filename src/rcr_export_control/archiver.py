# -*- coding: utf-8 -*-
from bs4 import element
from copy import deepcopy
from itertools import chain
from lxml import etree
from rcr_export_control.xml_tools import convert_tag_type
from rcr_export_control.xml_tools import convert_galleys
from rcr_export_control.xml_tools import convert_supplemental_files
from rcr_export_control.xml_tools import extract_reference_pmids
from rcr_export_control.xml_tools import get_archive_content_base_id
from rcr_export_control.xml_tools import get_archive_id
from rcr_export_control.xml_tools import get_index_from_figure_ref
from rcr_export_control.xml_tools import get_namespaced_attribute
from rcr_export_control.xml_tools import is_internal
from rcr_export_control.xml_tools import is_media_url
from rcr_export_control.xml_tools import parse_article_html
from rcr_export_control.xml_tools import set_namespaced_attribute
from rcr_export_control.xml_tools import set_sec_type
from rcr_export_control.xml_tools import DateParserXSLTExtension
from textwrap import TextWrapper

import os
import re
import requests
import zipfile


HOME = os.path.dirname(__file__)


class JATSArchiver(object):
    """handles converting PHP exported JATS to PMC compliant zip archive"""
    
    parsed_xml = None
    out_path = None
    reference_tree = None
    current_figure_node = None
    base_filename = None
    inner_basename = None
    current_figure_images = []
    current_caption_tags = []
    converted = False
    figure_list = []
    galley_storage = {}
    supplemental_storage = {}
    media_files_to_archive = {}
    files_to_archive = {}
    compression = zipfile.ZIP_STORED
    pubmed_base_url = "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    base_query = {
        'db': 'pubmed',
        'version': '2.0',
    }


    def __init__(self, parsed, out_path, log_level=0):
        self.parsed_xml = parsed
        self.out_path = out_path
        if log_level:
            if log_level > 3:
                log_level = 3
            self.log_level = log_level
        else:
            self.log_level = 0
        self.text_wrapper = TextWrapper(
            initial_indent="   ", subsequent_indent="   "
        )
        self.base_filename = get_archive_id(self.parsed_xml)
        self.inner_basename = get_archive_content_base_id(self.base_filename)
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
        cooked = {
            'xml': self.parsed_xml,
            'galleys': self.galley_files,
            'supplemental': self.supplemental_files,
        }
        return cooked

    @property
    def transform(self):
        if not hasattr(self, '_transform'):
            transform_path = os.path.join(HOME, 'pubmed_jats_transform.xsl')
            with open(transform_path) as fh:
                date_parser = DateParserXSLTExtension()
                extensions = { ('rcr_namespace', 'parse-date'): date_parser, }
                self._transform = etree.XSLT(
                    etree.XML(fh.read()), extensions=extensions
                )
        return self._transform

    # Public API

    def convert(self):
        """iteratively build body sections"""
        # then, parse the exported HTML body of the document and transform it
        # to JATS XML
        body = self.parsed_xml.find('body')
        if 'markup' in self.raw:
            if self.raw['markup'] is None:
                raise ValueError('exported xml has no page markup')
            html = parse_article_html(self.raw['markup'])
            ref_ids = extract_reference_pmids(html)
            self._handle_references(ref_ids)

            header_tags = html.find_all('p', class_='subheading')
            # XXX this should be logging to an output stream
            self._log_msg(
                "Processing {0} potential sections".format(len(header_tags)),
                level=1
            )

            for header_tag in header_tags:
                heading = header_tag.text
                sec_node = None
                if heading not in ['Abstract', 'References']:
                    # XXX this should be logging to an output stream
                    self._log_msg(
                        "Building Section using subheading",
                        "{0}\n".format(heading),
                        level=2
                    )
                    # dump abstract, it's elsewhere
                    # handle references separately
                    sec_node = etree.SubElement(body, 'sec')
                    sec_node.tail = "\n"
                    set_sec_type(sec_node, heading)
                    sec_title = etree.SubElement(sec_node, 'title')
                    sec_title.tail = "\n"
                    sec_title.text = heading
                    self._build_section(sec_node, header_tag)

            # append references and other back matter to the JATS document
            self._append_back_matter()

            # finally, resolve internal cross-references 
            # (refs, media and figures)
            self._handle_crosslinks()

            # ensure that if there is a pdf galley, it is written to the 
            # archive
            self._handle_pdf_galley()

        self.converted = True


    def archive(self):
        """write the results of conversion out to a zip file archive"""
        if not self.converted:
            raise RuntimeError('must call archiver.convert() before archiving')
        archive_name = self.base_filename + '.zip'
        archive_path = os.path.join(self.out_path, archive_name)
        archive = zipfile.ZipFile(
            archive_path, 'w', compression=self.compression
        )
        xml_filename = self.inner_basename + '.xml'
        archive.writestr(
            xml_filename, etree.tostring(
                self.parsed_xml,
                encoding='utf-8',
                xml_declaration=True,
                pretty_print=True
            )
        )
        # archive any additional files set up during processing, these should
        # be stored in a dict with the archive name as the key and the 
        # filesystem path as the stored value
        for name, path in self.files_to_archive.items():
            archive.write(path, name, self.compression)
        for name, path in self.media_files_to_archive.items():
            archive.write(path, name, self.compression)
        archive.close()

    # Private API

    def _log_msg(self, header=None, msg=None, level=4):
        """log script feedback and warning messages

        level indicates the number of 'q' flags needed to suppress output. If
        the number of flags passed on the command line meets or exceed this
        value, the statement will be suppressed.

        At the moment, this simply prints all messages to stdout.  It would
        be good to replace this with more configurable logging.
        """
        if not (header or msg):
            return

        if level - self.log_level <= 0:
            return

        if header is not None:
            print header
        if msg is not None:
            print self.text_wrapper.fill(msg)
        print "\n"

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
                self._log_msg(
                    "Investigating Tag", "{0}\n".format(tag), level=1
                )
                comp = map(str.lower, tag.get('class', ['']))
                if 'subheading' in comp:
                    # stop when we reach the next subheading
                    self._log_msg(
                        "Ending section on new subheading",
                        "{0}\n".format(tag),
                        level=3
                    )
                    break
                elif 'figure' in comp:
                    # this is a figure.  Deal with it.
                    f_node = etree.SubElement(sec_node, 'fig')
                    self._process_figure(f_node, tag)
                elif tag.name == 'p':
                    # if the article has yet to be converted to using the
                    # 'figure' class on figure paragraphs, try to catch
                    # figures anyway.
                    if tag.find(class_="figureCaption") is not None or tag.find('img') is not None:
                        # this is a figure.  Deal with it.
                        if self.current_figure_node is None:
                            self.current_figure_node = etree.SubElement(
                                sec_node, 'fig'
                            )
                        self._process_malformed_figure(tag)
                    elif 'figurecaption' in comp:
                        if self.current_figure_node is None:
                            self.current_figure_node = etree.SubElement(
                                sec_node, 'fig'
                            )
                        self._process_malformed_figure(tag)
                    else:
                        p_node = etree.SubElement(sec_node, 'p')
                        self._process_paragraph(p_node, tag)
                        p_node.tail = "\n"
                elif tag.name in ['ul', 'ol']:
                    l_node = etree.SubElement(sec_node, 'list')
                    self._process_list(l_node, tag)
                elif tag.name == 'table':
                    wrap_node = etree.SubElement(sec_node, 'table-wrap')
                    self._insert_tag(wrap_node, tag)
                # we will also need to special-case handling definition
                # lists here.  grrrr.

            elif isinstance(tag, element.NavigableString):
                # XXX Log navigable strings with non-whitespace in case we're
                #     missing something important
                self._log_msg(
                    "Unprocessed text at document root level",
                    "'{0}'\n".format(tag),
                    level=1,
                )


    def _process_paragraph(self, p_node, p_tag):
        """iteratively process the children of an HTML paragraph tag"""
        self._log_msg("Processing paragraph", "{0}\n".format(p_tag), level=2)
        tailable = None

        for tag in p_tag.children:
            if isinstance(tag, element.NavigableString):
                insert = unicode(tag.string)
                # XXX: process inline references to bibliography and 
                #      figures here?
                if tailable is None:
                    current = p_node.text or ''
                    p_node.text = current + insert
                else:
                    current_tail = tailable.tail or ''
                    tailable.tail = current_tail + insert
                    tailable = None
            elif isinstance(tag, element.Tag):
                # special cases for anchors, br tags and lists
                if tag.name.lower() == 'a':
                    tailable = self._process_link(p_node, tag)
                elif tag.name.lower() == 'br':
                    current_node_text = p_node.text or ''
                    p_node.text = current_node_text + (tag.tail or '')
                elif tag.name.lower() in ['ol', 'ul']:
                    l_node = etree.SubElement(p_node, 'list')
                    self._process_list(l_node, tag)
                    tailable = l_node
                else:
                    tailable = self._insert_tag(p_node, tag)

    def _process_list(self, l_node, l_tag):
        """process lists properly"""
        self._log_msg(
            "Processing list", "{0}\n".format(l_tag), level=1
        )
        list_types = {'ul': 'bullet', 'ol': 'order'}
        l_node.attrib['list-type'] = list_types[l_tag.name]

        for li_tag in l_tag.find_all('li'):
            li_node = etree.SubElement(l_node, 'list-item')
            self._insert_tag(li_node, li_tag)
            li_node.tail = "\n"

    def _process_figure(self, f_node, f_tag):
        """figures must be processed out properly"""
        self._log_msg(
            "Processing well-formed figure", "{0}\n".format(f_tag), level=2
        )
        self.figure_list.append(f_node)
        self._set_figure_id(f_node)
        for caption_tag in f_tag.find_all('span', class_='figureCaption'):
            self._log_msg(
                "Appending figure caption", "{0}\n", level=1)
            caption_tag.name = 'p'
            caption_node = etree.SubElement(f_node, 'caption')
            caption_p = etree.SubElement(caption_node, 'p')
            self._process_paragraph(caption_p, caption_tag)
            caption_node.tail = "\n"
        for img_tag in f_tag.find_all('img'):
            self._log_msg(
                "Appending figure graphic", "{0}\n", level=1)
            graphic_node = self._insert_tag(f_node, img_tag)
            set_namespaced_attribute(
                graphic_node, 'href', img_tag['src'], prefix='xlink'
            )
            graphic_node.tail = "\n"
        f_node.tail = "\n"


    def _process_malformed_figure(self, f_tag):
        """handle figures that are spread among several concurrent paragraphs"""
        self._log_msg(
            "Processing malformed figure", "{0}\n".format(f_tag), level=2
        )
        f_node = self.current_figure_node
        if f_node not in self.figure_list:
            self.figure_list.append(f_node)
            self._set_figure_id(f_node)
        figure_images = f_tag.find_all('img')
        if len(figure_images) > 0:
            # this node contains images, store them and move on
            self.current_figure_images.extend(figure_images)
            self._log_msg(
                "Preparing {0} graphics for figure".format(len(figure_images)),
                "{0}\n".format(" ".join(map(str, figure_images))),
                level=1
            )
        if f_tag.find(class_='figureCaption') is not None or\
            'figureCaption' in f_tag.get('class', []):
            # this node is the caption, time to process it all
            if 'figureCaption' in f_tag.get('class', []) and f_tag.text:
                self.current_caption_tags = [f_tag]
            else:
                self.current_caption_tags = f_tag.find_all(
                    'span', class_='figureCaption'
                )

        if self.current_figure_images and self.current_caption_tags:
            for caption_tag in self.current_caption_tags:
                self._log_msg(
                    "Processing figure caption",
                    "{0}\n".format(caption_tag),
                    level=1
                )
                caption_tag.name = 'p'
                caption_node = etree.SubElement(f_node, 'caption')
                caption_p = etree.SubElement(caption_node, 'p')
                self._process_paragraph(caption_p, caption_tag)
                caption_node.tail = "\n"
            for img_tag in self.current_figure_images:
                self._log_msg(
                    "Appending figure graphic",
                    "{0}\n".format(img_tag),
                    level=1
                )
                graphic_node = self._insert_tag(f_node, img_tag)
                set_namespaced_attribute(
                    graphic_node, 'href', img_tag['src'], prefix='xlink'
                )
                graphic_node.tail = "\n"
            f_node.tail = "\n"
            # empty out the buffers we've stored for processing this figure
            self._log_msg("Figure processing complete", level=2)
            self._clear_stored_figure()
        # else:
        #     msg_head = "ERROR: there has been a problem processing the figure "
        #     msg_head += "associated with this tag.  Please check your article "
        #     msg_head += "source HTML."
        #     self._log_msg(msg_head, "{0}\n".format(f_tag))
        #     # empty out the buffers we've stored for processing this figure
        #     self._clear_stored_figure()


    def _clear_stored_figure(self):
        """clear the storage used for iteratively processing figures"""
        self.current_figure_node = None
        self.current_figure_images = []
        self.current_caption_tags = []

    def _insert_tag(self, node, tag, subnode_type=None):
        """insert a subnode based on node"""
        self._log_msg("Inserting tag", "{0}\n".format(tag), level=1)
        if subnode_type is None:
            subnode_type = convert_tag_type(tag)

        # for tag types that should be eliminated outright ('br')
        if subnode_type is None:
            return None

        tailable = None
        subnode = etree.SubElement(node, subnode_type)
        subnode.tail = "\n"

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


    def _insert_email_tag(self, node, tag):
        """create an 'email' tag from the mailto: anchor tag passed in"""
        # XXX: Implement This
        raise NotImplementedError


    def _insert_media_tag(self, node, tag):
        self._log_msg(
            "Inserting media tag for element", "{0}\n".format(tag), level=2
        )
        media_node = etree.SubElement(node, 'media')
        subnode = etree.SubElement(media_node, 'label')
        set_namespaced_attribute(media_node, 'href', tag['href'], 'xlink')
        tailable = None
        for child in tag.children:
            if isinstance(child, element.NavigableString):
                insert = unicode(child.string)
                if tailable is None:
                    subnode.text = insert
                else:
                    tailable.tail = insert
                    tailable = None
            elif isinstance(child, element.Tag):
                tailable = self._insert_tag(subnode, child)

        return media_node


    def _process_link(self, node, tag):
        """convert html links into cross-reference tags for JATS"""
        self._log_msg(
            "Processing xref link for element", '{0}\n'.format(tag), level=2
        )
        href = tag['href']
        if is_media_url(href):
            subnode = self._insert_media_tag(node, tag)
        elif 'mailto' in href:
            subnode = self._insert_email_tag(node, tag)
        else:
            subnode = self._insert_tag(node, tag)
            if subnode is not None:
                set_namespaced_attribute(
                    subnode, 'href', tag['href'], prefix='xlink'
                )

        return subnode


    def _handle_references(self, ids):
        """build reference tree from a list of pubmed ids

        The tree is built by querying the PubMed esummary eutil for docsummary
        xml. This is then transformed through xslt into a JATS-compliant ref-list
        element and that element is returned.
        """
        bad_slots = []
        orig_count = len(ids)
        if None in ids:
            msg = "There have been references found with no links to pubmed. "
            msg += "These references cannot be properly processed.  Please "
            msg += "check the output xml from this article to manually "
            msg += "resolve the issue."
            self._log_msg("ERROR: in processing references", msg)
            fixed_ids = []
            for idx, pmid in enumerate(ids):
                if pmid is None:
                    bad_slots.append(idx)
                else:
                    fixed_ids.append(pmid)
            ids = fixed_ids

        if orig_count != len(ids):
            msg = "Looking up {count} of {orig} references"
        else:
            msg = "Looking up {count} references"
        self._log_msg(
            msg.format(**{'count': len(ids), 'orig': orig_count}),
            level=1
        )
        query = {'id': ','.join(ids)}
        query.update(self.base_query)
        resp = requests.get(self.pubmed_base_url, params=query)
        if resp.ok:
            # must pass a byte-string to the parser
            source = etree.XML(resp.content)
            for idx in bad_slots:
                self._log_msg(
                    "ERROR",
                    'Bad reference {0}, inserting placeholder'.format(idx + 1)
                )
                container = source.find('.//DocumentSummarySet')
                new = etree.Element('DocumentSummary')
                new.append(etree.Element('error'))
                new.attrib['uid'] = 'INSERTED_PLACEHOLDER'
                # the DBBuild element is always element 0 in the list of 
                # children, so in reality the index of summaries will be 
                # 1-based.
                container.insert(idx + 1, new)
            # check the resulting tree for error elements
            err_nodes = source.findall('.//error')
            for err_node in err_nodes:
                # there has been an error in the request for data that did not
                # result in a failed request, usually due to some reference 
                # PMID failing to return data.  Report the problem:
                uid = "Unidentified PMID"
                for parent in err_node.iterancestors():
                    if parent.tag.lower() == 'documentsummary':
                        uid = parent.attrib['uid']
                        break

                # we've already warned about placeholders we are inserting
                # so skip alerting a second time for those.
                if uid != 'INSERTED_PLACEHOLDER':
                    msg = "There was an error in PubMed processing PMID "
                    msg += "{0}. Please check the resulting exported XML "
                    msg += "for errors in the reference section."
                    self._log_msg("ERROR", msg.format(uid))

            self.reference_tree = self.transform(source)
            self._log_msg("References parsed and transformed", level=1)
        else:
            self._log_msg("ERROR", "Reference lookup failed")
            raise IOError


    def _append_back_matter(self):
        if self.reference_tree is not None:
            back = etree.SubElement(self.parsed_xml.getroot(), 'back')
            ref_list = deepcopy(self.reference_tree).getroot()
            if ref_list is not None:
                back.append(ref_list)


    def _set_figure_id(self, f_node):
        tmpl = 'fig-{0}'
        f_node.attrib['id'] = tmpl.format(self.figure_list.index(f_node) + 1)


    def _handle_crosslinks(self):
        """convert files and resolve of figure and reference links"""
        # begin by processing raw supplemental and galley files:
        self.galley_storage = convert_galleys(self.raw['galleys'])
        self.supplemental_storage = convert_supplemental_files(
            self.raw['supplemental_files']
        )
        self._resolve_figures()
        self._resolve_media_links()
        self._resolve_references()


    def _resolve_figures(self):
        """match figures to the textual references and fetch files to store"""
        self._prepare_figure_files()
        # iterate over all the paragraphs at the top of sections of the body
        # of our parsed article xml
        for paragraph in self.parsed_xml.findall('/body/sec/p'):
            self._process_node_for_figures(paragraph)

        pass


    def _process_node_for_figures(self, node):
        if node.text:
            text = node.text
            node.text = ''
            self._process_text_for_figures(node, text)
        for child in node:
            self._process_node_for_figures(child)
        if node.tail:
            text = node.tail
            node.tail = ''
            self._process_text_for_figures(node, text, False)


    def _process_text_for_figures(self, node, text, as_text=True):
        fig_pat = re.compile('([\(\[]{1}fig[s]?\.)', re.I|re.M)
        id_pat = re.compile('([\da-zA-Z-]{1,5})', re.I|re.M)
        # if text.startswith('Followup angiography demonstrated'):
        #     import pdb; pdb.set_trace( )
        inserted = None
        found_figure = False
        attr = 'text'
        if not as_text:
            attr = 'tail'
        while text:
            if not found_figure:
                # search for figures
                parts = fig_pat.split(text, 1)
                if len(parts) == 3:
                    # we have found a figure.  Append all text up to and including
                    # the start of the reference to the parent node text and move
                    # on.
                    head, match, text = parts
                    if inserted is not None:
                        current_tail = inserted.tail or ''
                        inserted.tail = current_tail + head + match
                    else:
                        current = getattr(node, attr)
                        setattr(node, attr, current + head + match)
                    found_figure = True
                else:
                    if inserted is not None:
                        current_tail = inserted.tail or ''
                        inserted.tail = current_tail + parts[0]
                    else:
                        current = getattr(node, attr)
                        setattr(node, attr, current + parts[0])
                    return
            else:
                parts = id_pat.split(text, 1)
                if len(parts) == 3:
                    head, match, text = parts
                    # place the head part which is just plain text
                    if inserted is not None:
                        current_tail = inserted.tail or ''
                        inserted.tail = current_tail + head
                    else:
                        current = getattr(node, attr)
                        setattr(node, attr, current + head)
                    # get the id from the match, build an xref and insert it
                    # then place the match into it as text
                    fig_index = get_index_from_figure_ref(match)
                    if fig_index is not None:
                        try:
                            fig_id = self.figure_list[fig_index].attrib['id']
                        except IndexError:
                            msg = "Unable to find figure {0} while resolving "
                            msg += "figure references.  Please check the "
                            msg += "original html."
                            self._log_msg('ERROR', msg.format(match))
                            fig_id = "placeholder"
                        # XXX: at this point, if as_text is false, then inserted
                        # should be generated as the next sibling of node, not as
                        # a sub-element
                        if as_text:
                            inserted = etree.SubElement(node, 'xref')
                        else:
                            # preserve the tail of the current node since we'll 
                            # lose it when we addnext
                            orig_tail = node.tail
                            node.addnext(etree.Element('xref'))
                            # replace the tail of the current node
                            node.tail = orig_tail
                            # set inserted to the next node we just added
                            inserted = node.getnext()
                            # and chop off the tail we got thereby:
                            inserted.tail = ''
                            # replace the reference to the current node with 
                            # inserted
                            node = inserted
                        inserted.text = match
                        inserted.attrib['rid'] = fig_id
                        inserted.attrib['ref-type'] = 'fig'
                    else:
                        # this condition arises when we have figure references
                        # like "(Figs 1A, C)".  at this point, the parts 
                        # are (', ', 'C', ')...').  For now, assume that the
                        # head and match should both be part of the existing 
                        # inserted xref and the remainder should be treated
                        # as text for continuing processing.
                        msg = "Unable to find a viable figure index in the "
                        msg += "string {0}.  Please verify the linking of "
                        msg += "figures in the output JATS xml."
                        self._log_msg('WARNING', msg.format(match))
                        if inserted is not None:
                            current_text = inserted.text or ''
                            inserted.text = current_text + head + match
                        else:
                            current = getattr(node, attr)
                            setattr(node, attr, current + head + match)
                    # the remaining text might signal that we should stop, if
                    # this is the case, we are done finding a figure, set that
                    # to False so the next pass will 'do the right thing'
                    if not text or text[0] in [')', ']']:
                        found_figure = False
                else:
                    current = getattr(node, attr)
                    setattr(node, attr, current + parts[0])
                    return


    def _prepare_figure_files(self):
        """create archive names for figure files and update xml to match"""
        g_count = 1
        self._log_msg("Processing figure graphics files")
        for figure in self.figure_list:
            self._log_msg(
                "Processing graphics for figure",
                "{0}\n".format(etree.tostring(figure)),
                level=2
            )
            self._validate_figure(figure)
            for graphic in figure.findall('graphic'):
                filename = get_namespaced_attribute(
                    graphic, 'href', prefix='xlink'
                )
                filename = os.path.basename(filename)
                file_infos = []
                if filename:
                    try:
                        file_infos.extend(self._find_file_infos(
                            filename, self.galley_storage['html'][0]['images']
                        ))
                    except TypeError:
                        raise
                if len(file_infos) == 1:
                    file_info = file_infos[0]
                    new_filename = self._make_archive_filename(
                        file_info, g_count, 'g'
                    )
                    set_namespaced_attribute(
                        graphic, 'href', new_filename, prefix='xlink'
                    )
                    self.files_to_archive[new_filename] = file_info['path']
                    g_count += 1
                    self._log_msg(
                        "Built reference to graphic file",
                        "{0}\n".format(file_info['path']),
                        level=1
                    )
                else:
                    # we found more than one fileinfo.  At the moment this
                    # indicates an error condition, report the problem and 
                    # return.
                    msg = 'More than one possible file has been found for '
                    msg += 'figure graphic {0}'
                    self._log_msg("ERROR", msg.format(filename))


    def _validate_figure(self, fig_node):
        """report if a graphic is in a figure with a missing caption"""
        if fig_node.find('caption') is None or\
            fig_node.find('graphic') is None:
            msg = "malformed figure:\n{0}".format(etree.tostring(fig_node))
            self._log_msg("ERROR", msg)


    def _resolve_media_links(self):
        """fix up href attributes for media links"""
        self._log_msg("Resolving media links", level=3)
        media_links = self.parsed_xml.findall('//media')
        for link in media_links:
            href = get_namespaced_attribute(link, 'href', 'xlink')
            # if the href is internal, this points to a file on the server
            # and we must archive and fix the reference, otherwise, we can
            # leave it alone
            if is_internal(href):
                self._log_msg(
                    "Internal media link found",
                    "{0}\n".format(etree.tostring(link)),
                    level=2
                )
                filename = os.path.basename(href)
                file_infos = []
                file_infos.extend(self._find_file_infos(filename))
                if not file_infos:
                    file_infos.extend(
                        self._find_file_infos(filename, by_path=True)
                    )

                # one last check
                if file_infos:
                    file_info = file_infos[0]
                    if file_info is not None:
                        media_count = len(self.media_files_to_archive) + 1
                        new_filename = self._make_archive_filename(
                            file_info, media_count, 's'
                        )
                        self.media_files_to_archive[new_filename] = file_info['path']
                        set_namespaced_attribute(
                            link, 'href', new_filename, 'xlink'
                        )
                        self._log_msg(
                            "Linking to file",
                            "{0}\n".format(file_info['path']),
                            level=1
                        )

                    if len(file_infos) > 1:    
                        msg = "Unable to uniquely identify a candidate file "
                        msg += "from the link '{0}'. Using the first "
                        msg += "identified file from path '{1}'"
                        self._log_msg(
                            "WARNING", msg.format(href, file_info['path'])
                        )
                else:
                    msg = "Unable to resolve a reference to the media file "
                    msg += "'{0}' from link '{1}'. Please check the original "
                    msg += "and the output archive for this article."
                    self._log_msg('ERROR', msg.format(filename, href))


    def _resolve_references(self):
        """match references in back matter to inline citations"""
        self._log_msg("Processing inline citations", level=3)
        for paragraph in self.parsed_xml.findall('/body/sec/p'):
            self._process_node_for_references(paragraph)


    def _process_node_for_references(self, node):
        if node.text:
            text = node.text
            node.text = ''
            self._process_text_for_references(node, text)
        for child in node:
            self._process_node_for_references(child)
        if node.tail:
            text = node.tail
            node.tail = ''
            self._process_text_for_references(node, text, False)


    def _process_text_for_references(self, node, text, as_text=True):
        bibref_pat = re.compile('\(([\d,\s]+)\)', re.I|re.M)
        comma_pat = re.compile(',\s?', re.I|re.M)
        inserted = None
        attr = 'text'
        if not as_text:
            attr = 'tail'
        while text:
            parts = bibref_pat.split(text, 1)
            if len(parts) == 3:
                # we've found the marker we seek, process it
                head, match, text = parts
                self._log_msg(
                    "Processing inline citation to {0}".format(match),
                    level=1
                )
                # start by appending the part up to the match to the current
                # end of where we are.
                if inserted is not None:
                    current_tail = inserted.tail or ''
                    inserted.tail = current_tail + head + '('
                else:
                    current = getattr(node, attr)
                    setattr(node, attr, current + head + '(')
                text = ')' + text
                # then process each number found in the matched pattern
                refnums = comma_pat.split(match)
                for index, bibref_number in enumerate(refnums):
                    # XXX: insert level-1 logging here showing the reference
                    # that matches to this reference number, somehow.

                    # XXX: at this point, if as_text is false, then inserted
                    # should be generated as the next sibling of node, not as
                    # a sub-element
                    if as_text:
                        inserted = etree.SubElement(node, 'xref')
                    else:
                        # preserve the tail of the current node since we'll 
                        # lose it when we addnext
                        orig_tail = node.tail
                        node.addnext(etree.Element('xref'))
                        # replace the tail of the current node
                        node.tail = orig_tail
                        # set inserted to the next node we just added
                        inserted = node.getnext()
                        # and chop off the tail we got thereby:
                        inserted.tail = ''
                        # replace the reference to the current node with 
                        # inserted
                        node = inserted
                    inserted.text = bibref_number
                    inserted.attrib['rid'] = 'ref-{0}'.format(bibref_number)
                    inserted.attrib['ref-type'] = 'bibr'
                    if index + 1 < len(refnums):
                        inserted.tail = ', '
            else:
                if inserted is not None:
                    current_tail = inserted.tail or ''
                    inserted.tail = current_tail + parts[0]
                else:
                    current = getattr(node, attr)
                    setattr(node, attr, current + parts[0])
                return


    def _find_file_infos(
        self, key, location=None, default=(), by_path=False
    ):
        """search for files by filename in storage locations

        since there may possibly be more than one instance of a file stored
        by the same filename in different storages, always return a list of
        the files found, even if it is only one.
        """
        if location is not None:
            if not by_path:
                val = location.get(key, default)
                if val != default:
                    val = list(val)
                return val
            else:
                vals = []
                for infos in location.values():
                    for info in infos:
                        if 'path' in info and key in info['path']:
                            vals.extend(infos)
                            break
        else:
            possibles = []
            if not by_path:
                for location in [
                    self.galley_storage['html'][0].get('images', {}),
                    self.galley_storage['html'][0].get('files', {}),
                    self.supplemental_storage
                ]:
                    possible = location.get(key, default)
                    if possible != default:
                        possibles.append(possible)
            else:
                for infos in chain(*[
                    self.galley_storage['html'][0].get('images', {}).values(),
                    self.galley_storage['html'][0].get('files', {}).values(),
                    self.supplemental_storage.values()
                ]):
                    for info in infos:
                        if 'path' in info and key in info['path']:
                            possibles.extend(infos)
            return possibles or default


    def _make_archive_filename(self, file_info, count, prefix):
        """create filenames compliant with PMC standards

        see http://www.ncbi.nlm.nih.gov/pmc/pub/filespec-delivery/#naming-artd
        """
        ext = os.path.splitext(file_info['path'])[1]
        typ_name = '{0}{1:0>3}{2}'.format(prefix, count, ext)
        return '-'.join([self.inner_basename, typ_name])
        

    def _handle_pdf_galley(self):
        """generate name and place galley into archive files list"""
        self._log_msg("Archiving article PDF galley")
        pdf_galleys = self.galley_storage.get('pdf', [])
        possible = []
        file_path = None
        for galley in pdf_galleys:
            galley_files = galley.get('files', {})
            for galley_file in galley_files.values():
                for file_info in galley_file:
                    if 'path' in file_info:
                        possible.append(file_info['path'])
        if not possible:
            msg = "Unable to identify a pdf galley for this article."
            self._log_msg("ERROR", msg)
            return
        if len(possible) > 1:
            msg = "Unable to identify a unique pdf galley for this article. "
            msg += "Using the first identified file: {0}"
            self._log_msg("WARNING", msg.format(possible[0]), level=2)
        file_path = possible[0]
        file_name = "{0}.pdf".format(self.inner_basename)
        self.files_to_archive[file_name] = file_path
