# -*- coding: utf-8 -*-
from bs4 import element
from copy import deepcopy
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
    converted = False
    skip_next_paragraph = False
    figure_list = []
    galley_storage = {}
    supplemental_storage = {}
    files_to_archive = {}
    compression = zipfile.ZIP_STORED
    pubmed_base_url = "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    base_query = {
        'db': 'pubmed',
        'version': '2.0',
    }


    def __init__(self, parsed, out_path):
        self.parsed_xml = parsed
        self.out_path = out_path
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
                self._transform = etree.XSLT(etree.XML(fh.read()))
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

            # append references and other back matter to the JATS document
            self._append_back_matter()

            # finally, resolve internal cross-references 
            # (refs, media and figures)
            self._handle_crosslinks()

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
                # allow sub-processes to short-circuit the paragraph that 
                # follows them (helps in processing badly formatted figures)
                if self.skip_next_paragraph and tag.name == 'p':
                    self.skip_next_paragraph = False
                    continue
                # print "investigating tag: {0}\n\n".format(tag)
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
                        if tag.find(class_="figureCaption") is not None or tag.find('img') is not None:
                            print "found a figure by other means: {0}\n\n".format(tag)
                            # this is a figure.  Deal with it.
                            if self.current_figure_node is None:
                                self.current_figure_node = etree.SubElement(
                                    sec_node, 'fig'
                                )
                            self._process_malformed_figure(tag)
                        else:
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
        """figures must be processed out properly"""
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


    def _process_malformed_figure(self, f_tag):
        """handle figures that are spread among several concurrent paragraphs"""
        f_node = self.current_figure_node
        if f_node not in self.figure_list:
            self.figure_list.append(f_node)
            self._set_figure_id(f_node)
        figure_images = f_tag.find_all('img')
        if len(figure_images) > 0:
            # this node contains images, store them and move on
            self.current_figure_images.extend(figure_images)
        elif self.current_figure_images and\
            f_tag.find(class_='figureCaption') is not None:
            # this node is the caption, time to process it all
            for caption_tag in f_tag.find_all('span', class_='figureCaption'):
                caption_tag.name = 'p'
                caption_node = etree.SubElement(f_node, 'caption')
                caption_p = etree.SubElement(caption_node, 'p')
                self._process_paragraph(caption_p, caption_tag)
                caption_node.tail = "\n"
            for img_tag in self.current_figure_images:
                graphic_node = self._insert_tag(f_node, img_tag)
                set_namespaced_attribute(
                    graphic_node, 'href', img_tag['src'], prefix='xlink'
                )
                graphic_node.tail = "\n"
            f_node.tail = "\n"
            # empty out the buffers we've stored for processing this figure
            self._clear_stored_figure()
        else:
            msg = "there has been a problem processing the figure associated"
            msg += "with this tag:\n{0}\nPlease check your article html."
            print msg.format(f_tag)
            # empty out the buffers we've stored for processing this figure
            self._clear_stored_figure()


    def _clear_stored_figure(self):
        """clear the storage used for iteratively processing figures"""
        self.current_figure_node = None
        self.current_figure_images = []

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


    def _insert_email_tag(self, node, tag):
        """create an 'email' tag from the mailto: anchor tag passed in"""
        # XXX: Implement This
        raise NotImplementedError


    def _insert_media_tag(self, node, tag):
        subnode = etree.SubElement(node, 'media')
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
        href = tag['href']
        if 'mailto' in href:
            subnode = self._insert_email_tag(node, tag)
        else:
            if is_internal(href):
                # deal with internal links in one way
                # might be a media file, might be another paper
                if not is_media_url(href):
                    subnode = self._insert_tag(node, tag)
                else:
                    subnode = self._insert_media_tag(node, tag)
            else:
                # deal with external links in another way
                # might be a mailto, might be a link to some external resource
                subnode = self._insert_tag(node, tag)

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
        fig_pat = re.compile('(fig[s]?\.)', re.I|re.M)
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
                            msg = "unable to find figure {0} while resolving "
                            msg += "figure references.  Please check the "
                            msg += "original html."
                            print msg.format(match)
                        inserted = etree.SubElement(node, 'xref')
                        inserted.text = match
                        set_namespaced_attribute(
                            inserted, 'href', fig_id, 'xlink'
                        )
                    else:
                        # this condition arises when we have figure references
                        # like "(Figs 1A, C)".  at this point, the parts 
                        # are (', ', 'C', ')...').  For now, assume that the
                        # head and match should both be part of the existing 
                        # inserted xref and the remainder should be treated
                        # as text for continuing processing.
                        msg = "unable to find a viable index in the string "
                        msg += "{0}.  Please verify the linking of figures "
                        msg += "in the output JATS xml."
                        print msg.format(match)
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
        for figure in self.figure_list:
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
                        import pdb; pdb.set_trace( )
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
                else:
                    # we found more than one fileinfo.  At the moment this
                    # indicates an error condition, report the problem and 
                    # return.
                    msg = 'More than one possible file has been found for '
                    msg += 'figure graphic {0}'
                    print msg.format(filename)


    def _resolve_media_links(self):
        pass


    def _resolve_references(self):
        """match references in back matter to inline citations"""
        pass


    def _find_file_infos(self, key, location=None, default=None):
        """search for files by filename in storage locations

        since there may possibly be more than one instance of a file stored
        by the same filename in different storages, always return a list of
        the files found, even if it is only one.
        """
        if location is not None:
            val = location.get(key, default)
            if val != default:
                val = list(val)
            return val
        else:
            possibles = []
            for location in [self.galley_storage['html'][0].get('images', {}),
                             self.galley_storage['html'][0].get('files', {}),
                             self.supplemental_storage]:
                possible = location.get(key, default)
                if possible != default:
                    possibles.append(possible)
            return possibles or default


    def _make_archive_filename(self, file_info, count, prefix):
        """create filenames compliant with PMC standards

        see http://www.ncbi.nlm.nih.gov/pmc/pub/filespec-delivery/#naming-artd
        """
        ext = os.path.splitext(file_info['path'])[1]
        typ_name = '{0}{1:0>3}{2}'.format(prefix, count, ext)
        return '-'.join([self.inner_basename, typ_name])
        
