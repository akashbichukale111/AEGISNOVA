/**
 * AEGISNOVA Autonomous Patch Validator
 * Analyzes candidate diffs for safety, prohibited side-effects, test deletions, and blast radius.
 */

export interface PatchValidationReport {
  isValid: boolean;
  score: number; // 0 - 100
  checks: {
    name: string;
    passed: boolean;
    reason?: string;
  }[];
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
}

const PROHIBITED_PATTERNS = [
  /rm -rf \//,
  /process\.exit\(/,
  /eval\(/,
  /chmod 777/,
  /DROP TABLE/i,
  /DISABLE_SECURITY/i,
  /credentials\.secret/i
];

/**
 * Validate a synthesized patch string prior to pull request generation
 */
export function validatePatchProposal(patchDiff: string, filename: string): PatchValidationReport {
  const checks: PatchValidationReport['checks'] = [];
  let score = 100;

  // 1. Check non-empty patch
  if (!patchDiff || patchDiff.trim().length === 0) {
    return {
      isValid: false,
      score: 0,
      checks: [{ name: 'Diff Content Non-Empty', passed: false, reason: 'Patch is empty' }],
      riskLevel: 'CRITICAL'
    };
  }
  checks.push({ name: 'Diff Content Non-Empty', passed: true });

  // 2. Check for prohibited unsafe code patterns
  let patternViolations = 0;
  for (const pattern of PROHIBITED_PATTERNS) {
    if (pattern.test(patchDiff)) {
      patternViolations++;
      checks.push({
        name: `Prohibited Pattern Check (${pattern.source})`,
        passed: false,
        reason: 'Potentially dangerous payload detected in patch proposal'
      });
      score -= 30;
    }
  }
  if (patternViolations === 0) {
    checks.push({ name: 'Dangerous Payload Filter', passed: true });
  }

  // 3. Check for massive deletions (safety net against truncation)
  const lines = patchDiff.split('\n');
  const deletedLines = lines.filter(l => l.startsWith('-') && !l.startsWith('---')).length;
  const addedLines = lines.filter(l => l.startsWith('+') && !l.startsWith('+++')).length;

  if (deletedLines > 300 && addedLines < 10) {
    score -= 40;
    checks.push({
      name: 'Diff Line Ratio Sanity',
      passed: false,
      reason: `Large unilateral line deletion (${deletedLines} deleted vs ${addedLines} added)`
    });
  } else {
    checks.push({ name: 'Diff Line Ratio Sanity', passed: true });
  }

  // 4. Critical target verification
  const isProtectedPath = /(^|\/)(package\.json|\.env|\.github\/workflows)/i.test(filename);
  if (isProtectedPath) {
    score -= 10;
    checks.push({
      name: 'Protected Target Awareness',
      passed: true,
      reason: 'Target is a core configuration file; requires heightened verification'
    });
  }

  score = Math.max(0, Math.min(100, score));

  let riskLevel: PatchValidationReport['riskLevel'] = 'LOW';
  if (score < 50) riskLevel = 'CRITICAL';
  else if (score < 75) riskLevel = 'HIGH';
  else if (score < 90) riskLevel = 'MEDIUM';

  return {
    isValid: score >= 60 && patternViolations === 0,
    score,
    checks,
    riskLevel
  };
}
