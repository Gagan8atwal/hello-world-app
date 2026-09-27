import test from "node:test";
import assert from "node:assert/strict";
import {
  ALOS_BRANCH,
  ALOS_BROWSER_OWNER_SHA256,
  ALOS_OWNER_RESULT_SCHEMA,
  ALOS_PROJECT_KEY,
  ALOS_REPOSITORY,
  ALOS_ZERO_KEY_MODE,
  buildAlosAdmissionRequest,
  consumeAlosOwnerResult,
} from "../.alos/zero-key-consumer.mjs";

const sourceRevision = "a".repeat(40);
const admission = () =>
  buildAlosAdmissionRequest({
    projectId: "project-1",
    taskId: "task-1",
    agentId: "agent-1",
    correlationId: "correlation-1",
    sourceRevision,
  });

const validResult = () => ({
  schema: ALOS_OWNER_RESULT_SCHEMA,
  projectKey: ALOS_PROJECT_KEY,
  repository: ALOS_REPOSITORY,
  branch: ALOS_BRANCH,
  sourceRef: ALOS_BRANCH,
  sourceRevision,
  status: "SUCCEEDED",
  projectId: "project-1",
  taskId: "task-1",
  agentId: "agent-1",
  executionId: "exec-final",
  correlationId: "correlation-1",
  resultId: "result-1",
  allowedTools: ["browser.read", "browser.interact"],
  persistedAllowedToolsEnforced: true,
  actualAgentRun: true,
  runAgentExecuted: true,
  toolExecutorExecuted: true,
  orchestratorExecuted: true,
  sameOwnerBrowser: true,
  agentExecution: {
    mode: "runAgent-internal-deterministic-browser-planner",
    externalInference: false,
    provider: null,
    model: null,
  },
  inference: {
    mode: ALOS_ZERO_KEY_MODE,
    serverOwnedDeterministicPlanner: true,
    provider: null,
    model: null,
    requestedModel: null,
    endpoint: null,
    providerReceipts: [],
    externalModelCalls: 0,
    externalApiCalls: 0,
    paidCostUsd: 0,
  },
  browser: {
    ownerSha256: ALOS_BROWSER_OWNER_SHA256,
    security: {
      uid: 1000,
      gid: 1000,
      noNewPrivs: true,
      sandboxOverride: false,
    },
  },
  verifier: { invoked: true, rawEvidence: true, sameOwner: true },
  runs: [
    {
      status: "SUCCEEDED",
      actualAgentRun: true,
      runAgentExecuted: true,
      sourceRef: ALOS_BRANCH,
      sourceRevision,
      inferenceMode: ALOS_ZERO_KEY_MODE,
      modelInference: false,
      executionId: "exec-1",
      sessionIds: ["session-1-mobile", "session-1-desktop"],
      actions: [{ actionId: "action-1" }],
      evidence: [{ producedByExecution: "exec-1", producedByAction: "action-1" }],
      duplicateSideEffects: 0,
    },
    {
      status: "SUCCEEDED",
      actualAgentRun: true,
      runAgentExecuted: true,
      sourceRef: ALOS_BRANCH,
      sourceRevision,
      inferenceMode: ALOS_ZERO_KEY_MODE,
      modelInference: false,
      executionId: "exec-2",
      sessionIds: ["session-2-mobile", "session-2-desktop"],
      actions: ["action-2"],
      evidence: [{ producedByExecution: "exec-2", producedByAction: "action-2" }],
      duplicateSideEffects: 0,
    },
  ],
  reliability: { reopenProof: true, retryProof: false, duplicateSideEffects: 0 },
});

test("admission pins exact reconciled product source ref and revision", () => {
  const request = admission();
  assert.equal(request.sourceRef, ALOS_BRANCH);
  assert.equal(request.branch, ALOS_BRANCH);
  assert.equal(request.sourceRevision, sourceRevision);
});

test("accepts current-source result with exact permissions and correlated evidence", () => {
  const accepted = consumeAlosOwnerResult(validResult(), admission());
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.sameOwnerConsumed, true);
  assert.equal(accepted.sourceRevision, sourceRevision);
  assert.deepEqual(accepted.executionIds, ["exec-1", "exec-2"]);
});

test("rejects stale source revision", () => {
  const result = validResult();
  result.sourceRevision = "b".repeat(40);
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /source revision mismatch/);
});

test("rejects wrong source ref", () => {
  const result = validResult();
  result.branch = "main";
  result.sourceRef = "main";
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /wrong source ref/);
});

test("rejects privilege-expanded tool set", () => {
  const result = validResult();
  result.allowedTools.push("shell.exec");
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /browser permissions mismatch/);
});

test("rejects evidence not correlated to execution and action", () => {
  const result = validResult();
  result.runs[0].evidence[0].producedByExecution = "exec-other";
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /correlated evidence missing/);
});

test("rejects owner result identities that do not match admission", () => {
  const result = validResult();
  result.taskId = "task-other";
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /taskId does not match admission/);
});

test("rejects a result that claims external or non-deterministic Agent execution", () => {
  const result = validResult();
  result.agentExecution.externalInference = true;
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /deterministic runAgent mode not proven/);
});

test("rejects Browser session replay across the two persisted runs", () => {
  const result = validResult();
  result.runs[1].sessionIds[0] = result.runs[0].sessionIds[0];
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /duplicate session across runs/);
});

test("rejects a bounded run without both mobile and desktop Browser sessions", () => {
  const result = validResult();
  result.runs[0].sessionIds = ["session-only"];
  assert.throws(() => consumeAlosOwnerResult(result, admission()), /bounded Browser sessions missing/);
});
