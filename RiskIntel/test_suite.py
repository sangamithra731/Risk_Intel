import unittest
import json
from app import app, db, User, Lake, Alert, SimulationState

class RiskIntelTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_health_api(self):
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data['status'], 'OPERATIONAL')
        self.assertIn('components', data)

    def test_unauthenticated_redirect(self):
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])

    def test_login_flow(self):
        # Invalid credentials
        res = self.client.post('/login', data={'email': 'admin@riskintel.local', 'password': 'wrongpassword'}, follow_redirects=True)
        self.assertIn(b'Invalid email or password', res.data)

        # Valid admin login
        res = self.client.post('/login', data={'email': 'admin@riskintel.local', 'password': 'riskintel123'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Command Center', res.data)

    def test_views_with_admin(self):
        with self.client:
            # Login as Admin
            self.client.post('/login', data={'email': 'admin@riskintel.local', 'password': 'riskintel123'})

            routes = [
                '/dashboard',
                '/map',
                '/lakes',
                '/lake/1',
                '/monitoring',
                '/risk',
                '/explainability',
                '/impact',
                '/alerts',
                '/incidents',
                '/rescue',
                '/shelters',
                '/evacuation',
                '/resources',
                '/analytics',
                '/recovery',
                '/simulation',
                '/system-health',
                '/admin',
                '/audit-logs'
            ]
            for route in routes:
                res = self.client.get(route)
                self.assertEqual(res.status_code, 200, f"Failed on route {route}")

    def test_api_risk_predict(self):
        with self.client:
            self.client.post('/login', data={'email': 'monitor@riskintel.local', 'password': 'riskintel123'})
            payload = {
                'water_level': 110.0,
                'water_level_change': 3.5,
                'rainfall': 140.0,
                'temperature': 18.0,
                'ice_melt': 28.0,
                'glacier_stability': 35.0,
                'terrain_movement': 25.0,
                'seismic_activity': 2.1
            }
            res = self.client.post('/api/risk/predict', json=payload)
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertIn('risk_score', data)
            self.assertIn('risk_level', data)
            self.assertIn('confidence', data)
            self.assertIn('feature_importance', data)
            self.assertGreaterEqual(data['risk_score'], 50.0)

    def test_simulation_lifecycle(self):
        with self.client:
            self.client.post('/login', data={'email': 'authority@riskintel.local', 'password': 'riskintel123'})

            # 1. Reset simulation
            res = self.client.post('/api/simulation/reset')
            self.assertEqual(res.status_code, 200)

            # 2. Check status (should be 0)
            res = self.client.get('/api/simulation/status')
            data = json.loads(res.data)
            self.assertEqual(data['current_step'], 0)

            # 3. Start simulation (goes to step 1)
            res = self.client.post('/api/simulation/start')
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertEqual(data['current_step'], 1)

            # 4. Step simulation to Step 2
            res = self.client.post('/api/simulation/step')
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertEqual(data['current_step'], 2)

    def test_alert_lifecycle(self):
        with self.client:
            self.client.post('/login', data={'email': 'authority@riskintel.local', 'password': 'riskintel123'})

            # Find a pending or recommended alert
            with app.app_context():
                alert = Alert.query.first()
                alert_id = alert.id

            # Approve alert
            res = self.client.post(f'/api/alerts/{alert_id}/approve')
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertEqual(data['alert']['status'], 'ACTIVE')

    def test_viewer_role_protection(self):
        with self.client:
            self.client.post('/login', data={'email': 'viewer@riskintel.local', 'password': 'riskintel123'})

            # Viewer can view dashboard
            res = self.client.get('/dashboard')
            self.assertEqual(res.status_code, 200)

            # Viewer CANNOT mutate state (POST /api/alerts/1/approve should return 403)
            res = self.client.post('/api/alerts/1/approve')
            self.assertEqual(res.status_code, 403)

if __name__ == '__main__':
    unittest.main()
