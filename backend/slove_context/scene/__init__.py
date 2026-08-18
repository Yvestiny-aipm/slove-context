"""Scene Card, in-story order, and dependencies (node 3.1).

Arcs and chapters are structure containers only. The generation unit is
a scene. Approving a Scene Card is not Canon approval and does not write
Canon. Generatable is a derived flag: approved (or published) card and
all dependency scenes approved or published.

Scene Plan jobs (node 3.3) consume the derived generatable flag.
Scene Draft generation is node 3.4 and is not implemented here.
"""
