# Contributing to AEGISNOVA

Thank you for your interest in contributing to AEGISNOVA — A New Standard for Safe AI!

AEGISNOVA is an open, governed autonomous software engineering platform built for verifiable trust. We welcome contributions from the community to improve security rules, agent capabilities, test harnesses, and UI components.

---

## 🛠️ Development Setup

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/akashbichukale111/AEGISNOVA.git
   cd AEGISNOVA
   ```

2. **Install Dependencies:**
   ```bash
   npm install
   ```

3. **Run Automated Smoke & Verification Suite:**
   ```bash
   npm test
   ```

4. **Start Local Development Server:**
   ```bash
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000) to view the application.

---

## 📋 Pull Request Guidelines

1. **Branch Naming:**
   - `feature/description` for new features or capabilities.
   - `fix/issue-description` for bug fixes.
   - `docs/topic` for documentation additions.

2. **Commit Conventions:**
   We follow standard Conventional Commits:
   - `feat(...)`: New feature or user-facing capability.
   - `fix(...)`: Bug fix or patch.
   - `docs(...)`: Documentation changes.
   - `test(...)`: Adding or updating test suites.
   - `refactor(...)`: Code refactoring without behavior change.
   - `ci(...)`: GitHub Actions or automation changes.

3. **Verification Invariant:**
   All PRs must pass `npm test` and `npm run build` with zero regressions before being merged.

---

## 🔒 Security & Token Hygiene

- **Never commit secrets:** Never commit API keys (`TAVILY_API_KEY`, `NEBIUS_API_KEY`, `GITHUB_TOKEN`, or private keys).
- All sensitive variables must reside in `.env.local` which is excluded by `.gitignore`.
