---
name: jev-scoring
description: Use Jev (jev-1.13-free) whenever a task needs scoring, judging, classifying, ranking, approval/sentiment detection, choosing between options, or a quality gate on text. Jev is a classifier, not a chat model — it answers typed questions about a JSON state with probabilities. Reach it through the codemode tool with models.classify. Never invent a score yourself when Jev can answer.
---

# Jev scoring & classification

Jev (`jev-1.13-free`, provider `100milionseek`) is a System One classifier
wired into this Pi. It does not chat. It takes a JSON **state** and a set of
typed **questions**, and returns answers with probabilities — fast and cheap
(0.2× quota). Use it when a task needs a judgement call:

- scoring text/code/answers against criteria
- yes/no gates (approved? safe? on-topic? complete?)
- picking one of several choices
- sentiment / intent / approval detection
- ranking or filtering items by a quality question

## How to call it (codemode tool only)

Classifier models never appear in the model picker. Use the `codemode`
tool and run a script:

```js
const jev = await models.getModelOfType("classifier", "100milionseek", "jev-1.13-free");
const result = await models.classify(jev, {
  state: { message: "The change works, thanks a lot!" },
  questions: {
    approved: {
      type: "bool",
      instructions: "Does the user approve of the result?",
      criteria: { true: "Approval", false: "No approval" },
    },
  },
});
return result.answers;
```

To check what classifiers exist: `models.getAvailableOfType("classifier")`.

## Question types

- `bool` — yes/no with probabilities for true/false.
- Choice — give a fixed set of options; Jev returns the pick + probabilities.
- Score — a numeric rating against your criteria.

Always write explicit `instructions` and `criteria` — Jev judges against
exactly what you state, nothing more. Keep the `state` focused: pass the
text/facts to judge, not the whole conversation.

## Rules

- Text input only on this provider (no images).
- If a call fails with a 502/503, the judge's upstream is congested — retry
  a few times with backoff. If it still fails, say so plainly and proceed
  without a score or ask; **never fabricate a score or probability**.
- Jev's answer is evidence, not an order — report its probabilities when
  they drive a decision.
