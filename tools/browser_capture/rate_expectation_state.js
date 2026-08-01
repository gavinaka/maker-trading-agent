import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';


export const RATE_ARTIFACTS = Object.freeze({
  cmeResult: 'cme_fedwatch_result.json',
  kalshiRaw: 'kalshi_feddecision_raw.json',
  normalized: 'fedwatch.json',
  primaryImage: 'fedwatch.png',
  provenance: 'rate_expectation_provenance.json',
});

const PRIMARY_SELECTED_ARTIFACTS = Object.freeze([
  RATE_ARTIFACTS.cmeResult,
  RATE_ARTIFACTS.primaryImage,
]);

const PLAN_C_SELECTED_ARTIFACTS = Object.freeze([
  RATE_ARTIFACTS.cmeResult,
  RATE_ARTIFACTS.normalized,
  RATE_ARTIFACTS.kalshiRaw,
]);


export function canonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const entries = Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value);
}


export function sha256Canonical(value) {
  return crypto.createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex');
}


export function hashRecord(record, hashField) {
  const clean = { ...record };
  delete clean[hashField];
  return sha256Canonical(clean);
}


export function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}


export function writeJsonAtomic(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.tmp`;
  const descriptor = fs.openSync(temporary, 'wx');
  try {
    try {
      fs.writeFileSync(descriptor, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
  } catch (error) {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    throw error;
  }
  try {
    fs.renameSync(temporary, filePath);
  } catch (error) {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    throw error;
  }
}


function exactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length
    && actual.every((key, index) => key === wanted[index]);
}


function validCaptureRunId(value) {
  return /^[0-9a-f-]{16,64}$/i.test(String(value || ''));
}


function validSha256(value) {
  return /^[0-9a-f]{64}$/.test(String(value || ''));
}


export function validateProviderContract(contract) {
  if (!contract || contract.schema_version !== 'fomc-rate-provider-contract-v1') {
    throw new Error('rate expectation provider contract schema is invalid');
  }
  const primary = contract.selection_modes?.cme_primary;
  const planC = contract.selection_modes?.kalshi_plan_c_fallback;
  if (
    primary?.provider_id !== 'cme_fedwatch_ui'
    || planC?.provider_id !== 'kalshi_public_market_data_api'
    || planC?.series_ticker !== contract.kalshi?.series_ticker
    || !Array.isArray(contract.cme?.eligible_fallback_codes)
    || !Array.isArray(contract.cme?.non_fallback_codes)
  ) {
    throw new Error('rate expectation provider contract is incomplete');
  }
  const eligible = new Set(contract.cme.eligible_fallback_codes);
  const blocked = new Set(contract.cme.non_fallback_codes);
  const attempt = contract.cme.attempt_artifact;
  const expectedAttemptFields = [
    'schema_version',
    'capture_run_id',
    'provider_id',
    'status',
    'defect_code',
    'started_at',
    'completed_at',
    'output',
    'attempt_sha256',
  ];
  const expectedStatusValues = ['passed', 'failed'];
  const expectedOutputFields = ['path', 'sha256', 'bytes'];
  if (
    eligible.size !== contract.cme.eligible_fallback_codes.length
    || blocked.size !== contract.cme.non_fallback_codes.length
    || [...eligible].some((code) => blocked.has(code))
  ) {
    throw new Error('CME fallback code sets are not closed and disjoint');
  }
  if (
    !attempt
    || JSON.stringify(attempt.exact_fields) !== JSON.stringify(expectedAttemptFields)
    || JSON.stringify(attempt.status_values) !== JSON.stringify(expectedStatusValues)
    || JSON.stringify(attempt.passed_output_exact_fields)
      !== JSON.stringify(expectedOutputFields)
    || attempt.passed_output_path !== RATE_ARTIFACTS.primaryImage
    || attempt.failed_output_must_be_null !== true
    || attempt.hash_field !== 'attempt_sha256'
    || attempt.hash_method_code !== 'sha256_canonical_json_without_self_v1'
  ) {
    throw new Error('CME attempt artifact contract is incomplete');
  }
  return contract;
}


export function validateCmeResult(result, contract) {
  validateProviderContract(contract);
  const attemptContract = contract.cme.attempt_artifact;
  const expectedKeys = attemptContract.exact_fields;
  if (!exactKeys(result, expectedKeys)) {
    throw new Error('CME result fields are not exact');
  }
  if (
    result.schema_version !== contract.cme_attempt_schema_version
    || result.provider_id !== contract.selection_modes.cme_primary.provider_id
    || !validCaptureRunId(result.capture_run_id)
    || !validSha256(result[attemptContract.hash_field])
    || result[attemptContract.hash_field]
      !== hashRecord(result, attemptContract.hash_field)
  ) {
    throw new Error('CME result identity or hash is invalid');
  }
  const started = Date.parse(result.started_at);
  const completed = Date.parse(result.completed_at);
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started) {
    throw new Error('CME result timestamps are invalid');
  }
  if (result.status === attemptContract.status_values[0]) {
    if (
      result.defect_code !== null
      || !exactKeys(result.output, attemptContract.passed_output_exact_fields)
    ) {
      throw new Error('passed CME result output is invalid');
    }
    if (
      result.output.path !== attemptContract.passed_output_path
      || !validSha256(result.output.sha256)
      || !Number.isInteger(result.output.bytes)
      || result.output.bytes <= 0
    ) {
      throw new Error('passed CME result artifact is invalid');
    }
  } else if (result.status === attemptContract.status_values[1]) {
    if (
      typeof result.defect_code !== 'string'
      || !result.defect_code
      || (attemptContract.failed_output_must_be_null && result.output !== null)
    ) {
      throw new Error('failed CME result is invalid');
    }
  } else {
    throw new Error('CME result status is invalid');
  }
  return result;
}


export function decideProvider(result, contract) {
  validateCmeResult(result, contract);
  if (result.status === 'passed') {
    return Object.freeze({
      action: 'select_primary',
      selection_mode: 'cme_primary',
      provider_id: contract.selection_modes.cme_primary.provider_id,
      fallback_reason_code: 'none',
    });
  }
  if (contract.cme.eligible_fallback_codes.includes(result.defect_code)) {
    return Object.freeze({
      action: 'attempt_plan_c_once',
      selection_mode: 'kalshi_plan_c_fallback',
      provider_id: contract.selection_modes.kalshi_plan_c_fallback.provider_id,
      fallback_reason_code: result.defect_code,
    });
  }
  return Object.freeze({
    action: 'hard_stop',
    selection_mode: null,
    provider_id: null,
    fallback_reason_code: result.defect_code,
  });
}


export function decideFullCaptureFallback(failedScripts, providerSummary) {
  if (!Array.isArray(failedScripts) || failedScripts.some((item) => typeof item !== 'string')) {
    throw new Error('failedScripts must be an array of script names');
  }
  if (!failedScripts.length) {
    return Object.freeze({ run_full_fallback: false, suppressed_reason_code: null });
  }
  if (failedScripts.includes('capture_rate_expectation.js')) {
    return Object.freeze({
      run_full_fallback: false,
      suppressed_reason_code: 'rate_expectation_capture_failed',
    });
  }
  if (providerSummary?.provider_fallback_used === true) {
    return Object.freeze({
      run_full_fallback: false,
      suppressed_reason_code: 'plan_c_attempt_already_consumed',
    });
  }
  return Object.freeze({ run_full_fallback: true, suppressed_reason_code: null });
}


export function buildProvenance({
  captureRunId,
  contract,
  selectionMode,
  fallbackReasonCode,
}) {
  validateProviderContract(contract);
  if (!validCaptureRunId(captureRunId)) throw new Error('invalid provenance capture_run_id');
  let payload;
  if (selectionMode === 'cme_primary') {
    if (fallbackReasonCode !== 'none') {
      throw new Error('primary provenance cannot contain a fallback reason');
    }
    payload = {
      schema_version: contract.provenance_schema_version,
      logical_source: contract.logical_source,
      capture_run_id: captureRunId,
      selection_mode: 'cme_primary',
      provider_id: contract.selection_modes.cme_primary.provider_id,
      series_ticker: null,
      fallback_reason_code: 'none',
      primary_attempt_artifact_path: RATE_ARTIFACTS.cmeResult,
      raw_artifact_paths: [],
      normalized_artifact_path: null,
      selected_artifact_paths: [...PRIMARY_SELECTED_ARTIFACTS],
      provenance_sha256: '',
    };
  } else if (selectionMode === 'kalshi_plan_c_fallback') {
    if (!contract.cme.eligible_fallback_codes.includes(fallbackReasonCode)) {
      throw new Error('Plan C provenance requires an eligible CME failure code');
    }
    payload = {
      schema_version: contract.provenance_schema_version,
      logical_source: contract.logical_source,
      capture_run_id: captureRunId,
      selection_mode: 'kalshi_plan_c_fallback',
      provider_id: contract.selection_modes.kalshi_plan_c_fallback.provider_id,
      series_ticker: contract.selection_modes.kalshi_plan_c_fallback.series_ticker,
      fallback_reason_code: fallbackReasonCode,
      primary_attempt_artifact_path: RATE_ARTIFACTS.cmeResult,
      raw_artifact_paths: [RATE_ARTIFACTS.kalshiRaw],
      normalized_artifact_path: RATE_ARTIFACTS.normalized,
      selected_artifact_paths: [...PLAN_C_SELECTED_ARTIFACTS],
      provenance_sha256: '',
    };
  } else {
    throw new Error(`unsupported rate expectation selection mode: ${selectionMode}`);
  }
  payload.provenance_sha256 = hashRecord(payload, 'provenance_sha256');
  return payload;
}


export function validateProvenance(payload, captureRunId, contract) {
  validateProviderContract(contract);
  const expectedKeys = [
    'schema_version',
    'logical_source',
    'capture_run_id',
    'selection_mode',
    'provider_id',
    'series_ticker',
    'fallback_reason_code',
    'primary_attempt_artifact_path',
    'raw_artifact_paths',
    'normalized_artifact_path',
    'selected_artifact_paths',
    'provenance_sha256',
  ];
  if (!exactKeys(payload, expectedKeys)) {
    throw new Error('rate expectation provenance fields are not exact');
  }
  if (
    !validCaptureRunId(payload.capture_run_id)
    || payload.capture_run_id !== captureRunId
    || !validSha256(payload.provenance_sha256)
    || payload.provenance_sha256 !== hashRecord(payload, 'provenance_sha256')
  ) {
    throw new Error('rate expectation provenance identity or hash is invalid');
  }
  if (
    payload.schema_version !== contract.provenance_schema_version
    || payload.logical_source !== contract.logical_source
  ) {
    throw new Error('rate expectation provenance contract identity is invalid');
  }

  const expected = payload.selection_mode === 'cme_primary'
    ? {
      provider: contract.selection_modes.cme_primary.provider_id,
      series: null,
      raw: [],
      normalized: null,
      selected: PRIMARY_SELECTED_ARTIFACTS,
    }
    : payload.selection_mode === 'kalshi_plan_c_fallback'
      ? {
        provider: contract.selection_modes.kalshi_plan_c_fallback.provider_id,
        series: contract.selection_modes.kalshi_plan_c_fallback.series_ticker,
        raw: [RATE_ARTIFACTS.kalshiRaw],
        normalized: RATE_ARTIFACTS.normalized,
        selected: PLAN_C_SELECTED_ARTIFACTS,
      }
      : null;
  if (!expected) throw new Error('rate expectation selection_mode is invalid');
  if (
    payload.provider_id !== expected.provider
    || payload.series_ticker !== expected.series
    || payload.primary_attempt_artifact_path !== RATE_ARTIFACTS.cmeResult
    || JSON.stringify(payload.raw_artifact_paths) !== JSON.stringify(expected.raw)
    || payload.normalized_artifact_path !== expected.normalized
    || JSON.stringify(payload.selected_artifact_paths) !== JSON.stringify(expected.selected)
  ) {
    throw new Error('rate expectation provenance artifact selection is invalid');
  }
  if (
    payload.selection_mode === 'cme_primary'
      ? payload.fallback_reason_code !== 'none'
      : !contract.cme.eligible_fallback_codes.includes(payload.fallback_reason_code)
  ) {
    throw new Error('rate expectation fallback reason is invalid');
  }
  for (const artifactPath of payload.selected_artifact_paths) {
    if (path.basename(artifactPath) !== artifactPath) {
      throw new Error('rate expectation artifact path must be a basename');
    }
  }
  return payload;
}


export function providerSummaryFromProvenance(payload, captureRunId, contract) {
  validateProvenance(payload, captureRunId, contract);
  return {
    schema_version: payload.schema_version,
    selection_mode: payload.selection_mode,
    provider_id: payload.provider_id,
    series_ticker: payload.series_ticker,
    provider_fallback_used: payload.selection_mode === 'kalshi_plan_c_fallback',
    fallback_reason_code: payload.fallback_reason_code,
    provenance_path: RATE_ARTIFACTS.provenance,
    provenance_sha256: payload.provenance_sha256,
  };
}
