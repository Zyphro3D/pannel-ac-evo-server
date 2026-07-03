// Test de fumée : vérifie que les pages principales du panel se chargent
// sans erreur JS/console et que l'authentification fonctionne.
//
// Nécessite un panel démarré (docker compose up -d) et des identifiants
// superadmin valides fournis via variables d'environnement :
//   PANEL_TEST_USERNAME, PANEL_TEST_PASSWORD
// Sans ces variables, les tests nécessitant une session sont ignorés.
//
// Lancement : npx playwright test

const { test, expect } = require('@playwright/test');

const TEST_USERNAME = process.env.PANEL_TEST_USERNAME;
const TEST_PASSWORD = process.env.PANEL_TEST_PASSWORD;

const PUBLIC_PAGES = ['/', '/login', '/register', '/results', '/timing'];
const ADMIN_PAGES = ['/server', '/drivers', '/events', '/settings', '/live'];

function collectPageErrors(page) {
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(err.message));
  return errors;
}

for (const path of PUBLIC_PAGES) {
  test(`page publique sans erreur console : ${path}`, async ({ page }) => {
    const errors = collectPageErrors(page);
    const response = await page.goto(path);
    expect(response.ok()).toBeTruthy();
    expect(errors, `Erreurs console sur ${path} : ${errors.join(' | ')}`).toEqual([]);
  });
}

test.describe('Session admin', () => {
  test.skip(!TEST_USERNAME || !TEST_PASSWORD, 'PANEL_TEST_USERNAME / PANEL_TEST_PASSWORD non définis');

  // Sélecteurs par id plutôt que par label : le panel est traduit en 5 langues
  // (fr/en/de/es/it), un texte de label en dur casserait le test selon la
  // langue du navigateur.
  async function login(page) {
    await page.goto('/login');
    await page.locator('#username-input').fill(TEST_USERNAME);
    await page.locator('#pwd-input').fill(TEST_PASSWORD);
    await page.locator('#login-form button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);
  }

  test('connexion superadmin', async ({ page }) => {
    await login(page);
  });

  for (const path of ADMIN_PAGES) {
    test(`page admin sans erreur console : ${path}`, async ({ page }) => {
      await login(page);

      const errors = collectPageErrors(page);
      const response = await page.goto(path);
      expect(response.ok()).toBeTruthy();
      expect(errors, `Erreurs console sur ${path} : ${errors.join(' | ')}`).toEqual([]);
    });
  }
});
