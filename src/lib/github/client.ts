/**
 * AEGISNOVA — GitHub Client & Connection Service
 * ==============================================
 * Handles GitHub App/PAT authentication, repository access verification,
 * repository discovery, and branch/PR generation with strict security boundaries.
 * 
 * Invariants:
 * - Tokens are NEVER stored in browser client storage or sent in client responses.
 * - Public repositories are readable even without a token where GitHub rate limits permit.
 * - Private repositories require an authenticated token.
 * - Write operations (branch/PR) require explicit user authorization.
 */

import { GitHubConnection, RepositoryTarget, PullRequestResult } from "@/contracts";
import path from "path";
import fs from "fs";

export interface NormalizedRepoInfo {
  owner: string;
  repo: string;
  fullName: string;
  isLocalFixture: boolean;
  localPath?: string;
}

/**
 * Normalize GitHub URL or slug (e.g. "https://github.com/owner/repo" or "owner/repo")
 */
export function normalizeGitHubUrl(input: string): NormalizedRepoInfo | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  // Local fixture shorthand
  if (trimmed.startsWith("demo/")) {
    const fixtureName = trimmed.replace("demo/", "");
    const localPath = path.resolve(process.cwd(), "services/nightshift-sde/fixtures/demo-repos", fixtureName);
    return {
      owner: "demo",
      repo: fixtureName,
      fullName: trimmed,
      isLocalFixture: true,
      localPath
    };
  }

  // HTTP or SSH URL
  let slug = trimmed;
  if (slug.startsWith("https://github.com/")) {
    slug = slug.replace("https://github.com/", "");
  } else if (slug.startsWith("http://github.com/")) {
    slug = slug.replace("http://github.com/", "");
  } else if (slug.startsWith("git@github.com:")) {
    slug = slug.replace("git@github.com:", "");
  }

  // Remove .git and trailing slashes
  slug = slug.replace(/\.git$/, "").replace(/\/+$/, "");

  const parts = slug.split("/");
  if (parts.length >= 2 && parts[0] && parts[1]) {
    return {
      owner: parts[0],
      repo: parts[1],
      fullName: `${parts[0]}/${parts[1]}`,
      isLocalFixture: false
    };
  }

  return null;
}

/**
 * Retrieve GitHub connection status
 */
export async function getGitHubConnectionStatus(): Promise<GitHubConnection> {
  const token = process.env.GITHUB_TOKEN;

  if (!token) {
    return {
      status: "UNCONFIGURED",
      tokenConfigured: false
    };
  }

  try {
    const res = await fetch("https://api.github.com/user", {
      headers: {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": `Bearer ${token}`,
        "User-Agent": "AEGISNOVA-Safe-AI"
      },
      cache: "no-store"
    });

    const rateRemaining = parseInt(res.headers.get("x-ratelimit-remaining") || "0", 10);
    const rateLimitReset = res.headers.get("x-ratelimit-reset") || undefined;
    const scopesHeader = res.headers.get("x-oauth-scopes") || "";
    const scopes = scopesHeader.split(",").map(s => s.trim()).filter(Boolean);

    if (res.status === 401) {
      return {
        status: "INVALID_TOKEN",
        tokenConfigured: true,
        rateLimitRemaining: rateRemaining,
        rateLimitReset
      };
    }

    if (res.status === 403 && rateRemaining === 0) {
      return {
        status: "RATE_LIMITED",
        tokenConfigured: true,
        rateLimitRemaining: 0,
        rateLimitReset
      };
    }

    if (res.ok) {
      const user = await res.json();
      return {
        status: "CONNECTED",
        username: user.login,
        avatarUrl: user.avatar_url,
        scopes,
        tokenConfigured: true,
        rateLimitRemaining: rateRemaining,
        rateLimitReset
      };
    }

    return {
      status: "UNCONFIGURED",
      tokenConfigured: true
    };
  } catch (error) {
    return {
      status: "UNCONFIGURED",
      tokenConfigured: true
    };
  }
}

/**
 * Verify access to a repository (Public check or Private with Token)
 */
export async function verifyRepositoryAccess(urlOrSlug: string): Promise<{
  verified: boolean;
  repoTarget?: RepositoryTarget;
  isPrivate?: boolean;
  permissions?: { push: boolean; pull: boolean };
  defaultBranch?: string;
  commitSha?: string;
  error?: string;
}> {
  const normalized = normalizeGitHubUrl(urlOrSlug);
  if (!normalized) {
    return { verified: false, error: "Invalid repository URL or slug format. Expected 'owner/repo' or 'https://github.com/owner/repo'." };
  }

  // Check local fixture repository
  if (normalized.isLocalFixture && normalized.localPath) {
    if (fs.existsSync(normalized.localPath)) {
      return {
        verified: true,
        repoTarget: {
          id: normalized.fullName,
          name: normalized.repo,
          path: normalized.localPath,
          defaultBranch: "main",
          testCommand: "python -m unittest discover -s tests",
          buildManifest: "requirements.txt",
          isMonitored: true
        },
        isPrivate: false,
        permissions: { push: true, pull: true },
        defaultBranch: "main",
        commitSha: "local-fixture-sha-881a"
      };
    } else {
      return { verified: false, error: `Local fixture not found at ${normalized.localPath}` };
    }
  }

  // Remote GitHub repository verification
  const token = process.env.GITHUB_TOKEN;
  const headers: Record<string, string> = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "AEGISNOVA-Safe-AI"
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const res = await fetch(`https://api.github.com/repos/${normalized.owner}/${normalized.repo}`, {
      headers,
      cache: "no-store"
    });

    if (res.status === 404) {
      return {
        verified: false,
        error: token
          ? "Repository not found or token lacks read access."
          : "Repository not found or is private (GITHUB_TOKEN required to access private repositories)."
      };
    }

    if (res.status === 403) {
      const remaining = res.headers.get("x-ratelimit-remaining");
      if (remaining === "0") {
        return { verified: false, error: "GitHub API rate limit exceeded. Please configure GITHUB_TOKEN to increase quota." };
      }
      return { verified: false, error: "Forbidden: Token lacks permissions for this repository." };
    }

    if (!res.ok) {
      return { verified: false, error: `GitHub API error: HTTP ${res.status}` };
    }

    const data = await res.json();
    return {
      verified: true,
      repoTarget: {
        id: data.full_name,
        name: data.name,
        path: `github:${data.full_name}`,
        defaultBranch: data.default_branch || "main",
        testCommand: "Discovered from repository manifests upon intake",
        buildManifest: "Auto-detected",
        isMonitored: true
      },
      isPrivate: data.private,
      permissions: {
        push: Boolean(data.permissions?.push),
        pull: Boolean(data.permissions?.pull ?? true)
      },
      defaultBranch: data.default_branch || "main"
    };
  } catch (error) {
    return { verified: false, error: `Network error verifying repository: ${(error as Error).message}` };
  }
}

/**
 * List available repositories (Local fixtures + accessible remote repos if token present)
 */
export async function listAvailableRepositories(): Promise<RepositoryTarget[]> {
  const targets: RepositoryTarget[] = [
    {
      id: "demo/payments-service",
      name: "payments-service",
      path: "services/nightshift-sde/fixtures/demo-repos/payments-service",
      defaultBranch: "main",
      testCommand: "python -m unittest discover -s tests",
      buildManifest: "requirements.txt",
      isMonitored: true
    },
    {
      id: "demo/legacy-batch",
      name: "legacy-batch",
      path: "services/nightshift-sde/fixtures/demo-repos/legacy-batch",
      defaultBranch: "main",
      testCommand: "python -m unittest discover -s tests",
      buildManifest: "requirements.txt",
      isMonitored: true
    },
    {
      id: "demo/conflict-lab",
      name: "conflict-lab",
      path: "services/nightshift-sde/fixtures/demo-repos/conflict-lab",
      defaultBranch: "main",
      testCommand: "python -m unittest discover -s tests",
      buildManifest: "requirements.txt",
      isMonitored: true
    },
    {
      id: "demo/node-storefront",
      name: "node-storefront",
      path: "services/nightshift-sde/fixtures/demo-repos/node-storefront",
      defaultBranch: "main",
      testCommand: "npm test",
      buildManifest: "package.json",
      isMonitored: true
    }
  ];

  // If token is configured, append accessible remote repositories
  const token = process.env.GITHUB_TOKEN;
  if (token) {
    try {
      const res = await fetch("https://api.github.com/user/repos?per_page=15&sort=updated", {
        headers: {
          "Accept": "application/vnd.github.v3+json",
          "Authorization": `Bearer ${token}`,
          "User-Agent": "AEGISNOVA-Safe-AI"
        },
        cache: "no-store"
      });
      if (res.ok) {
        const remoteRepos = await res.json();
        remoteRepos.forEach((r: any) => {
          targets.push({
            id: r.full_name,
            name: r.name,
            path: `github:${r.full_name}`,
            defaultBranch: r.default_branch || "main",
            testCommand: "Auto-detected on checkout",
            buildManifest: "Auto-detected",
            isMonitored: false
          });
        });
      }
    } catch {
      // Graceful fallback to local fixtures
    }
  }

  return targets;
}
