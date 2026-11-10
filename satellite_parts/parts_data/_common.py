"""Helpers for part records. See ../SCHEMA.md for the field meanings."""

ACCESSED = "2026-11-08"


def source(kind, url, document=None, fields=None, notes="", revision=None, date=None):
    return {"type": kind, "url": url, "document": {"title": document, "revision": revision, "date": date}, "accessed": ACCESSED, "fields_from_source": fields or [], "notes": notes}


def cost(value=None, currency="USD", basis="unknown", source_url=None):
    return {"value": value, "currency": currency, "basis": basis, "source": source_url}


def part(id, name, category, subcategory, vendor, model, dims, mass_g, shape, src, **extra):
    """dims = (x, y, z) mm as packed. extra: any schema fields (status, vendor_country, first_available_year, material, electrical, adcs, ...)."""
    record = {"id": id, "name": name, "category": category, "subcategory": subcategory, "vendor": vendor, "model": model, "dimensions_mm": {"x": dims[0], "y": dims[1], "z": dims[2]}, "mass_g": mass_g, "shape": shape, "source": src}
    record.setdefault("status", "unknown")
    record.setdefault("fidelity", "envelope")
    record.update(extra)
    return record
