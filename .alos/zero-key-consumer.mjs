export const ALOS_PROJECT_KEY = "on-alert-media";
export const ALOS_PROJECT_NAME = "On Alert / DOX / Case Zero";
export const ALOS_REPOSITORY = "Gagan8atwal/hello-world-app";
export const ALOS_BRANCH = "on-alert-media-temp";
export const ALOS_ZERO_KEY_MODE = "deterministic-zero-key";
export const ALOS_BROWSER_OWNER_SHA256 = "43e0adec2c7d53cb79dcf5ca3d4b4e2c66ccd16ed917eddbf3cab0cf73a214a1";
export const ALOS_ADMISSION_SCHEMA = "alos.project-admission.v1";
export const ALOS_OWNER_RESULT_SCHEMA = "alos.project-owner-result.v1";

const TOOLS = Object.freeze(["browser.read", "browser.interact"]);
const ID = /^[A-Za-z0-9._:-]{1,192}$/;
const REVISION = /^[0-9a-f]{40,64}$/i;
const need = (condition, message) => {
  if (!condition) throw new Error(`ALOS_CONSUMER_REJECTED: ${message}`);
};
const valid = (value) => typeof value === "string" && ID.test(value);
const validRevision = (value) => typeof value === "string" && REVISION.test(value);
const exactTools = (actual) =>
  Array.isArray(actual) &&
  actual.length === TOOLS.length &&
  new Set(actual).size === TOOLS.length &&
  TOOLS.every((tool) => actual.includes(tool));
const actionIdentity = (action) =>
  typeof action === "string" ? action : action?.actionId ?? action?.id;

export function buildAlosAdmissionRequest({
  projectId,
  taskId,
  agentId,
  correlationId,
  sourceRevision,
}) {
  for (const [key, value] of Object.entries({ projectId, taskId, agentId, correlationId })) {
    need(valid(value), `${key} is required`);
  }
  need(validRevision(sourceRevision), "sourceRevision must be an exact git revision");

  return Object.freeze({
    schema: ALOS_ADMISSION_SCHEMA,
    projectKey: ALOS_PROJECT_KEY,
    projectName: ALOS_PROJECT_NAME,
    repository: ALOS_REPOSITORY,
    branch: ALOS_BRANCH,
    sourceRef: ALOS_BRANCH,
    sourceRevision,
    projectId,
    taskId,
    agentId,
    correlationId,
    requiredAllowedTools: TOOLS,
    inference: Object.freeze({
      mode: ALOS_ZERO_KEY_MODE,
      provider: null,
      model: null,
      providerCredentialRequired: false,
      externalModelCalls: 0,
      maxPaidCostUsd: 0,
      serverOwnedDeterministicPlanner: true,
    }),
    browser: Object.freeze({
      ownerSha256: ALOS_BROWSER_OWNER_SHA256,
      requireNonRoot: true,
      requireNoNewPrivs: true,
      forbidSandboxOverride: true,
    }),
    mintsExecutionIdentity: false,
    mintsPermissionGrant: false,
    acceptsModelAuthorization: false,
  });
}

export function consumeAlosOwnerResult(result, admission) {
  need(result && typeof result === "object" && !Array.isArray(result), "result object required");
  need(admission && typeof admission === "object" && !Array.isArray(admission), "admission object required");
  need(admission.schema === ALOS_ADMISSION_SCHEMA, "wrong admission schema");
  need(admission.projectKey === ALOS_PROJECT_KEY, "wrong admission project");
  need(admission.repository === ALOS_REPOSITORY, "wrong admission repository");
  need(admission.branch === ALOS_BRANCH && admission.sourceRef === ALOS_BRANCH, "wrong admission source ref");
  need(validRevision(admission.sourceRevision), "invalid admission source revision");

  need(result.schema === ALOS_OWNER_RESULT_SCHEMA, "wrong schema");
  need(result.projectKey === ALOS_PROJECT_KEY, "wrong project");
  need(result.repository === ALOS_REPOSITORY, "wrong repository");
  need(result.branch === ALOS_BRANCH && result.sourceRef === ALOS_BRANCH, "wrong source ref");
  need(result.sourceRevision === admission.sourceRevision, "source revision mismatch");
  need(result.status === "SUCCEEDED", "execution did not succeed");

  for (const field of ["projectId", "taskId", "agentId", "correlationId"]) {
    need(valid(result[field]), `${field} missing or invalid`);
    need(result[field] === admission[field], `${field} does not match admission`);
  }
  for (const field of ["executionId", "resultId"]) {
    need(valid(result[field]), `${field} missing or invalid`);
  }

  need(exactTools(result.allowedTools), "browser permissions mismatch");
  need(result.persistedAllowedToolsEnforced === true, "persisted permissions not enforced");
  need(
    result.actualAgentRun === true &&
      result.runAgentExecuted === true &&
      result.toolExecutorExecuted === true &&
      result.orchestratorExecuted === true,
    "shared Agent/Router path not proven",
  );
  need(
    result.agentExecution?.mode === "runAgent-internal-deterministic-browser-planner" &&
      result.agentExecution?.externalInference === false &&
      result.agentExecution?.provider === null &&
      result.agentExecution?.model === null,
    "deterministic runAgent mode not proven",
  );
  need(result.sameOwnerBrowser === true, "same owner Browser not proven");

  const inference = result.inference;
  need(
    inference?.mode === ALOS_ZERO_KEY_MODE && inference?.serverOwnedDeterministicPlanner === true,
    "wrong inference mode",
  );
  for (const field of ["provider", "model", "requestedModel", "endpoint"]) {
    need(inference?.[field] === null, `${field} must be null`);
  }
  need(Array.isArray(inference?.providerReceipts) && inference.providerReceipts.length === 0, "provider receipts forbidden");
  need(
    inference?.externalModelCalls === 0 && inference?.externalApiCalls === 0 && inference?.paidCostUsd === 0,
    "external calls/cost detected",
  );

  const browser = result.browser;
  need(browser?.ownerSha256 === ALOS_BROWSER_OWNER_SHA256, "wrong Browser owner hash");
  need(
    browser?.security?.uid > 0 &&
      browser?.security?.gid > 0 &&
      browser?.security?.noNewPrivs === true &&
      browser?.security?.sandboxOverride === false,
    "Browser security mismatch",
  );
  need(
    result.verifier?.invoked === true &&
      result.verifier?.rawEvidence === true &&
      result.verifier?.sameOwner === true,
    "raw verifier evidence missing",
  );

  need(Array.isArray(result.runs) && result.runs.length === 2, "exactly two bounded runs required");
  const executionIds = new Set();
  const sessionIds = new Set();
  for (const run of result.runs) {
    need(
      run?.status === "SUCCEEDED" &&
        run?.actualAgentRun === true &&
        run?.runAgentExecuted === true,
      "bounded run failed",
    );
    need(run?.sourceRef === ALOS_BRANCH, "bounded run source ref mismatch");
    need(run?.sourceRevision === admission.sourceRevision, "bounded run source revision mismatch");
    need(run?.inferenceMode === ALOS_ZERO_KEY_MODE && run?.modelInference === false, "bounded inference mismatch");
    need(valid(run?.executionId) && !executionIds.has(run.executionId), "duplicate execution");
    executionIds.add(run.executionId);

    need(
      Array.isArray(run?.sessionIds) &&
        run.sessionIds.length >= 2 &&
        run.sessionIds.every(valid),
      "bounded Browser sessions missing",
    );
    need(new Set(run.sessionIds).size === run.sessionIds.length, "duplicate session within run");
    for (const sessionId of run.sessionIds) {
      need(!sessionIds.has(sessionId), "duplicate session across runs");
      sessionIds.add(sessionId);
    }

    need(Array.isArray(run?.actions) && run.actions.length > 0, "Browser actions missing");
    need(Array.isArray(run?.evidence), "correlated evidence missing");
    const actionIds = run.actions.map(actionIdentity);
    need(actionIds.every(valid), "Browser action identity missing");
    need(new Set(actionIds).size === actionIds.length, "duplicate Browser action identity");
    for (const actionId of actionIds) {
      need(
        run.evidence.some(
          (evidence) =>
            evidence?.producedByExecution === run.executionId &&
            evidence?.producedByAction === actionId,
        ),
        "correlated evidence missing",
      );
    }
    need(run?.duplicateSideEffects === 0, "duplicate side effects");
  }

  need(result.reliability?.retryProof === true || result.reliability?.reopenProof === true, "retry/reopen proof required");
  need(result.reliability?.duplicateSideEffects === 0, "duplicate side effects");

  return Object.freeze({
    accepted: true,
    projectKey: ALOS_PROJECT_KEY,
    projectId: result.projectId,
    sourceRef: ALOS_BRANCH,
    sourceRevision: admission.sourceRevision,
    executionIds: Object.freeze([...executionIds]),
    inferenceMode: ALOS_ZERO_KEY_MODE,
    browserOwnerSha256: ALOS_BROWSER_OWNER_SHA256,
    sameOwnerConsumed: true,
    paidCostUsd: 0,
  });
}
