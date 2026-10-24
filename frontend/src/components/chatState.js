export const MAX_HISTORY_MESSAGES_BEFORE_USER = 18;
export const MAX_HISTORY_CHARACTERS = 10000;

export function chatContextKey(premiseId, scenario, profile, utilityStatus) {
  return JSON.stringify({ premiseId, scenario, profile, utilityStatus });
}

// Keep complete user/assistant pairs so the next user turn remains valid for the backend.
export function boundedHistory(history, question) {
  const completed = history.length % 2 === 0 ? history : history.slice(0, -1);
  const pairs = [];
  for (let i = 0; i < completed.length; i += 2) pairs.push(completed.slice(i, i + 2));

  const kept = [];
  let characters = question.length;
  for (let i = pairs.length - 1; i >= 0; i -= 1) {
    const pair = pairs[i];
    const pairCharacters = pair.reduce((total, message) =>
      total + message.content.reduce((n, block) => n + block.text.length, 0), 0);
    if (kept.length + pair.length > MAX_HISTORY_MESSAGES_BEFORE_USER ||
        characters + pairCharacters > MAX_HISTORY_CHARACTERS) break;
    kept.unshift(...pair);
    characters += pairCharacters;
  }
  return [...kept, { role: "user", content: [{ text: question }] }];
}

export function createRequestGate() {
  let version = 0;
  let inFlight = false;
  let controller = null;

  return {
    invalidate() {
      version += 1;
      controller?.abort();
      controller = null;
      inFlight = false;
    },
    begin(contextKey) {
      if (inFlight) return null;
      inFlight = true;
      controller = new AbortController();
      return { version, contextKey, signal: controller.signal };
    },
    isCurrent(token, contextKey) {
      return Boolean(token) && token.version === version && token.contextKey === contextKey && !token.signal.aborted;
    },
    finish(token) {
      if (!token || token.version !== version) return false;
      inFlight = false;
      controller = null;
      return true;
    },
    isInFlight() { return inFlight; },
  };
}
