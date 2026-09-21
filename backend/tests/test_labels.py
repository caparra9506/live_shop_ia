"""Etiqueta local de la conversacion: python -m unittest discover -s tests -t ."""

import unittest
from types import SimpleNamespace

from app.labels import fill_empty_label


class FillEmptyLabelTests(unittest.TestCase):
    def test_pone_la_etiqueta_cuando_no_hay_ninguna(self):
        conv = SimpleNamespace(current_label=None)
        self.assertTrue(fill_empty_label(conv, "Nuevo contacto"))
        self.assertEqual(conv.current_label, "Nuevo contacto")

    def test_tambien_cuando_esta_vacia(self):
        conv = SimpleNamespace(current_label="")
        self.assertTrue(fill_empty_label(conv, "Nuevo contacto"))
        self.assertEqual(conv.current_label, "Nuevo contacto")

    def test_no_pisa_una_etiqueta_existente_ni_las_manuales(self):
        for existing in ("VIP", "En captura de cliente", "Cliente registrado"):
            conv = SimpleNamespace(current_label=existing)
            self.assertFalse(fill_empty_label(conv, "Nuevo contacto"))
            self.assertEqual(conv.current_label, existing)

    def test_sin_conversacion_o_sin_etiqueta_no_hace_nada(self):
        self.assertFalse(fill_empty_label(None, "Nuevo contacto"))
        conv = SimpleNamespace(current_label=None)
        self.assertFalse(fill_empty_label(conv, None))
        self.assertFalse(fill_empty_label(conv, ""))
        self.assertIsNone(conv.current_label)


if __name__ == "__main__":
    unittest.main()
