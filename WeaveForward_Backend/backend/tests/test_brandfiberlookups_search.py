from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from ..models import User, BrandFiberLookup

class BrandFiberLookupSearchTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639000000000",
            status="ACTIVE"
        )
        
        # Create sample data
        BrandFiberLookup.objects.create(category="Jeans", brand="Levi's", clothing_type="Pants", fiber_json='{"cotton": 100}', is_active=True)
        BrandFiberLookup.objects.create(category="T-Shirt", brand="Uniqlo", clothing_type="Tops", fiber_json='{"cotton": 100}', is_active=True)
        BrandFiberLookup.objects.create(category="Shirt", brand="Uniqlo", clothing_type="Tops", fiber_json='{"polyester": 50, "cotton": 50}', is_active=True)
        BrandFiberLookup.objects.create(category="Dress", brand="H&M", clothing_type="Dresses", fiber_json='{"silk": 100}', is_active=True)
        BrandFiberLookup.objects.create(category="Old Pants", brand="Levi's", clothing_type="Pants", fiber_json='{"cotton": 98, "elastane": 2}', is_active=False) # Inactive

    def test_unauthenticated_access_denied(self):
        response = self.client.get(reverse('material-clothing-types'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        response = self.client.get(reverse('material-brands'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        response = self.client.get(reverse('material-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_clothing_types(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('material-clothing-types'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should be sorted unique active clothing types
        expected = ["Dresses", "Pants", "Tops"]
        self.assertEqual(response.data, expected)

    def test_get_brands(self):
        self.client.force_authenticate(user=self.user)
        
        # All brands
        response = self.client.get(reverse('material-brands'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(response.data), ["H&M", "Levi's", "Uniqlo"])
        
        # Brands for Tops
        response = self.client.get(reverse('material-brands'), {'clothing_type': 'Tops'})
        self.assertEqual(response.data, ["Uniqlo"])
        
        # Brands for Pants
        response = self.client.get(reverse('material-brands'), {'clothing_type': 'Pants'})
        self.assertEqual(response.data, ["Levi's"])

    def test_search_items(self):
        self.client.force_authenticate(user=self.user)
        
        # Search by query 'Levi'
        response = self.client.get(reverse('material-list'), {'q': 'Levi'})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['brand'], "Levi's")
        
        # Search by clothing_type exactly
        response = self.client.get(reverse('material-list'), {'clothing_type': 'Tops'})
        self.assertEqual(len(response.data), 2)
        
        # Search by brand and clothing_type
        response = self.client.get(reverse('material-list'), {'brand': 'Uniqlo', 'clothing_type': 'Tops'})
        self.assertEqual(len(response.data), 2)

    def test_fibers_action(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('material-fibers'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # cotton, polyester, silk (elastane is from inactive record)
        self.assertEqual(response.data, ["cotton", "polyester", "silk"])
