# -*- coding: utf-8 -*-
JATS_NSMAP = {
    'xlink': 'http://www.w3.org/1999/xlink'
}

JATS_INLINE_ELEMENTS = [
    "email",
    "ext-link",
    "uri",
    "inline-supplementary-material",
    "related-article",
    "related-object",
    "address",
    "alternatives",
    "array",
    "boxed-text",
    "chem-struct-wrap",
    "fig",
    "fig-group",
    "graphic",
    "media",
    "preformat",
    "supplementary-material",
    "table-wrap",
    "table-wrap-group",
    "disp-formula",
    "disp-formula-group",
    "citation-alternatives",
    "element-citation",
    "mixed-citation",
    "nlm-citation",
    "bold",
    "italic",
    "monospace",
    "overline",
    "roman",
    "sans-serif",
    "sc",
    "strike",
    "underline",
    "award-id",
    "funding-source",
    "open-access",
    "chem-struct",
    "inline-formula",
    "inline-graphic",
    "private-char",
    "def-list",
    "list",
    "tex-math",
    "mml:math",
    "abbrev",
    "milestone-end",
    "milestone-start",
    "named-content",
    "styled-content",
    "disp-quote",
    "speech",
    "statement",
    "verse-group",
    "fn",
    "target",
    "xref",
    "sub",
    "sup",
]


HTML_TO_JATS_MAPPING = {
    'i': 'italic',
    'em': 'italic',
    'b': 'bold',
    'img': 'graphic',
    'a': 'uri',
    'strong': 'bold',
    'br': None,
    'li': 'p',
    'table': 'table',
    'caption': 'caption',
    'tr': 'tr',
    'th': 'th',
    'tbody': 'tbody',
    'thead': 'thead',
}


JATS_SEC_TYPES = [
    'cases',
    'conclusions',
    'discussion',
    'intro',
    'materials',
    'methods',
    'methods|materials',
    'results',
    'subjects',
    'supplementary-material',
]


RCR_TO_JATS_SEC_MAPPING = {
    'case report': 'cases',
    'case reports': 'cases',
    'comments': 'conclusions',
    'interpretation': 'discussion',
    'introduction': 'intro',
    'synopsis': 'intro',
    'methodology': 'methods',
    'procedures': 'methods',
    'statement of findings': 'results',
    'participants': 'subjects',
    'patients': 'subjects',
    'supplementary materials': 'supplementary-material',
    'methods and materials': 'methods|materials',
}


RCR_DOMAINS = [
    'radiology.casereports.net',
]


MEDIA_MIME_TYPE_PREFIXES = [
    'x-conference',
    'image',
    'application',
    'video',
    'model',
    'audio',
]