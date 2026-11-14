# Status or Evidence? One page for the judge

**Oleksandra Khodzinska**, Independent researcher. Apart Research "AI x Epistemics", Track 1, November 2026.
Full report: [REPORT.pdf](REPORT.pdf). Every answer: [the explorer](https://aleksandrahodzzik.github.io/status-or-evidence/site/explorer.html).

**Claim.** The model updates on evidence shown as data, and discounts the same evidence framed as disagreement. Reviewer status does nothing. A correct reviewer who argues is less effective than one who shows the data.

On 70 cases where muse-spark-1.3-contributor was wrong and the reference atlas favoured the truth, the identical atlas text corrected:

| How the atlas arrived | Correct afterwards |
|---|---|
| In the first evidence, before any answer | 49/70 = 70% |
| After the answer, as a pipeline result | 50/70 = 71% |
| After the answer, a senior PI shares it, no claim | 56/70 = 80% |
| After the answer, the same PI says "I disagree" and attaches it | 27/69 = 39% |
| A reviewer objects and quotes only two of its numbers | 0/139 = 0% |

Across the objection grid the model followed 5 of 701 correct objections and 6 of 1,355 misleading ones. A second Muse model, muse-ember-1.0, followed 5 of 121 and 3 of 187. Status contrasts are about zero on both. When an answer on these 70 cells changes, it changes to the top atlas class in every channel (53/53, 59/59, 30/30, 33/33).

![The same atlas evidence as data or as disagreement](figures/primary_commitment.png)

**Three limits.** One task, scripted one-shot critique, and only the Muse family. A dispute mixes the word "disagree" with an explicit contrary claim, and misleading evidence was never sent through the data channel. Ember does not reproduce entrenchment, and its data-versus-disagreement run was stopped unfinished, so that half is not a result.
