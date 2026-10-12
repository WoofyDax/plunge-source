"""The Plunge logo, drawn from simple geometry so it stays sharp at every size and needs no font.

MARK: a rounded square with a heavy rounded "P" (its bowl is open like a VR lens).
WORDMARK: PLUNGE in custom rounded letters: every letter is one thick stroke with round ends, so it feels friendly and chunky.
"""

# one letter is drawn in a 56 x 80 box with a 16-wide round stroke (so the ink fills the whole box)
LETTERS = {
    "P": "M8 72V8H30a18 18 0 0 1 0 36H8",
    "L": "M8 8V72H48",
    "U": "M8 8V52a20 20 0 0 0 40 0V8",
    "N": "M8 72V8L48 72V8",
    "G": "M43.3 19.4A20 32 0 1 0 47.8 44H30",
    "E": "M48 8H8V72H48M8 40H38",
}
WORD = "PLUNGE"
PITCH = 70                      # distance between letters
WORD_W, WORD_H = PITCH * (len(WORD) - 1) + 56, 80


def wordmark_paths():
    return "".join('<path transform="translate(%d 0)" d="%s"/>' % (i * PITCH, LETTERS[c]) for i, c in enumerate(WORD))


def wordmark(css_class="", height=None):
    """The lettering as an inline SVG that takes the surrounding text colour."""
    h = ' height="%s"' % height if height else ""
    c = ' class="%s"' % css_class if css_class else ""
    return ('<svg%s%s viewBox="-8 -8 %d %d" fill="none" stroke="currentColor" stroke-width="16" stroke-linecap="round" stroke-linejoin="round" '
            'role="img" aria-label="Plunge">%s</svg>') % (c, h, WORD_W + 16, WORD_H + 16, wordmark_paths())


_MARK_GRAD = '<defs><linearGradient id="%s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2aa0ff"/><stop offset="1" stop-color="#0a4dff"/></linearGradient></defs>'


def mark(css_class="", size=None, uid="pg"):
    """The icon: a blue rounded square with a white P."""
    s = ' width="%s" height="%s"' % (size, size) if size else ""
    c = ' class="%s"' % css_class if css_class else ""
    return ('<svg%s%s viewBox="0 0 256 256" role="img" aria-label="Plunge">%s<rect width="256" height="256" rx="62" fill="url(#%s)"/>'
            '<path d="M88 202V56h46a42 42 0 0 1 0 84H88" fill="none" stroke="#fff" stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>') % (c, s, _MARK_GRAD % uid, uid)


def full(css_class="", uid="pf"):
    """Mark and lettering side by side, as one standalone SVG file."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 128" role="img" aria-label="Plunge"><defs><linearGradient id="%s" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#2aa0ff"/><stop offset="1" stop-color="#0a4dff"/></linearGradient></defs>'
            '<g transform="scale(.5)"><rect width="256" height="256" rx="62" fill="url(#%s)"/>'
            '<path d="M88 202V56h46a42 42 0 0 1 0 84H88" fill="none" stroke="#fff" stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/></g>'
            '<g transform="translate(152 36) scale(.9)" fill="none" stroke="#fff" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">%s</g></svg>') % (uid, uid, wordmark_paths())
