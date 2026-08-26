from django.test import TestCase, Client
from django.urls import reverse
from store.models import Category, Product
from decimal import Decimal


class CartTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name="Classic Dill", slug="classic-dill")
        self.product = Product.objects.create(
            name="Kosher Dill Spears",
            slug="kosher-dill-spears",
            category=self.category,
            tagline="Crisp deli pickles",
            description="NYC style garlic dill spears",
            price_bdt=Decimal("380.00"),
            jar_weight_grams=500,
            is_in_stock=True
        )

    def test_cart_add_ajax(self):
        url = reverse('store:cart_add', args=[self.product.id])
        response = self.client.post(
            f"{url}?format=json",
            {'quantity': 2},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['cart_total_items'], 2)
        self.assertEqual(data['cart_subtotal'], 760.0)

    def test_cart_update_ajax(self):
        # Add item first
        add_url = reverse('store:cart_add', args=[self.product.id])
        self.client.post(add_url, {'quantity': 1})

        # Update increase
        update_url = reverse('store:cart_update_ajax')
        response = self.client.post(
            update_url,
            {'product_id': self.product.id, 'action': 'increase'},
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['item_quantity'], 2)
