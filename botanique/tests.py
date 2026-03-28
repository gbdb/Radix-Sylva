from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from botanique.models import Organism


class OrganismRequestViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('botanique.api_views.enrich_organism')
    def test_creates_organism_and_returns_200(self, mock_enrich):
        mock_enrich.return_value = {'vascan': (True, 'VASCAN : vascan_id=1')}
        url = reverse('organism-request')
        r = self.client.post(
            url,
            {'nom_latin': 'Testus requestus apivorus', 'nom_commun': 'Abeille des tests'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data['created'])
        self.assertFalse(r.data['matched_existing'])
        self.assertEqual(r.data['organism_id'], Organism.objects.get(nom_latin__iexact='Testus requestus apivorus').pk)
        mock_enrich.assert_called_once()
        args, kwargs = mock_enrich.call_args
        self.assertEqual(kwargs.get('sources'), ['vascan'])
        self.assertEqual(kwargs.get('delay'), 0)

    @patch('botanique.api_views.enrich_organism')
    def test_second_request_same_latin_is_idempotent(self, mock_enrich):
        mock_enrich.return_value = {'vascan': (False, 'VASCAN : aucune correspondance.')}
        url = reverse('organism-request')
        latin = 'Duplicateus plantus'
        self.client.post(url, {'nom_latin': latin}, format='json')
        oid = Organism.objects.get(nom_latin__iexact=latin).pk
        mock_enrich.reset_mock()
        r = self.client.post(url, {'nom_latin': latin}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data['created'])
        self.assertTrue(r.data['matched_existing'])
        self.assertEqual(r.data['organism_id'], oid)

    def test_requires_nom_latin(self):
        url = reverse('organism-request')
        r = self.client.post(url, {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
