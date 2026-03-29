---
name: white-rabbit
description: Introduction — what Parseltongue is and why it exists
---

# Follow the White Rabbit

> No one could ever be told the answer to that question. They have to see it to believe it.

## The Problem

> _You'd be surprised how illusory intelligence becomes once it needs to be proven explicitly._


Large language models don't know what truth is.

Despite the strong flavour of philosophical complaint, I mean this as an engineering fact. Even after processing the internet several times over, and passing training on pleasing humans, solving math puzzles, and coding purple landing pages - LLM agents still have no sense of truth.

What do I mean by "sense"? An absurd example: tomorrow everyone around you agrees that plastic vegetables make a good breakfast. It doesn't matter how many times they tell you, or even eat a piece to prove their point - you won't believe it. That's not the case for LLMs. You can call this human quality being grounded, or reasonable - the terminology doesn't matter much, as long as you get the sense of the problem.

Even when an LLM solves a math puzzle or a coding task, it reasons within the space of what it was trained on. And the bulk of that training was parroting the internet - which, I think we can all agree, is about as poor a source of truth as there can be, with a few notable exceptions.

The problem isn't that agents are stupid - it's that they are becoming very capable at exactly the tasks we train them for. Those include giving us pleasant answers that sometimes happen to be technically correct. This is great if you need a good conversation or a new website. It fundamentally doesn't work in high-stakes scenarios. We don't hire managers who excel at political bootlicking for a surgeon position - sometimes we simply need a different set of skills.

[[term:parseltongue]] is focusing on addressing the issue of making confident but entirely ungrounded statements. Here is what I mean:

```scheme
;; pltg The Origin

(defterm parseltongue "Parseltongue"
    :evidence (evidence "self"
      :quotes ("[[term:parseltongue]] is focusing on addressing")
      :explanation "Name"))

(load-document "self" "INTRO_WHITE-RABBIT.pg.md")

(fact the-next-sentence-is-grounded-in-parseltongue true
  :evidence (evidence "self"
    :quotes ("This sentence is grounded in Parseltongue[[~fact:the-next-sentence-is-grounded-in-parseltongue]]")
    :explanation "The sentence under this block became bound to the system"))

;; PS
;; Sorry if causality have cracked a bit. We were murdering the time, and now it's always six-o-clock here.
```
This sentence is grounded in Parseltongue[[~fact:the-next-sentence-is-grounded-in-parseltongue]]. And a few things happened: it became represented in the engine powering this documentation[[~fact:sentence-became-part-of-engine]]; and a fact representing this sentence was created. If you click the reference or the pill, you can locate it in the knowledge graph of this notebook, and in the layer of computations it will participate in next.

```scheme
;; pltg First steps
(fact sentence-became-part-of-engine true
  :evidence (evidence "self"
    :quotes ("And a few things happened: it became represented in the engine powering this documentation")
    :explanation "The second fact appeared."))

(import (quote std.std))
(import (quote std.counting c))

(derive count-facts-about-sentence 
    (c.count-exists 
        the-next-sentence-is-grounded-in-parseltongue
        sentence-became-part-of-engine) 
    :using (c.count-exists 
            the-next-sentence-is-grounded-in-parseltongue 
            sentence-became-part-of-engine))

```

If we count the facts about this sentence that we've introduced so far, we would probably all agree that there are [[derive:count-facts-about-sentence]] of them. This number was calculated by the derivation in the previous block, and if we changed the block - it would update.

What does all this have to do with LLMs lying? So far we were trying to express only the truth. Something interesting happens if we try to represent a lie - for example that [[fact:there-will-be-cake]]. As we can see, there is no cake - [[fact:the-cake-is-a-lie]]. But something interesting happens if we try to use those facts in our derivations: we normally calculate [[derive:count-facts-till-now]] truthful facts, but if we account for [[derive:accounting-for-a-lie]] - a lie becomes visible! The original lie taints the derivation - even though we can still see its result, we know that there was a lie in its basis.

```scheme
;; pltg The Fall
(fact the-cake-is-a-lie "The cake is a lie"
  :evidence (evidence "self"
    :quotes ("As we can see there is no cake")
    :explanation "Well, at least in this text"))

(derive count-facts-till-now 
    (c.count-exists 
        the-next-sentence-is-grounded-in-parseltongue
        sentence-became-part-of-engine
        the-cake-is-a-lie) 
    :using (c.count-exists 
            the-next-sentence-is-grounded-in-parseltongue 
            sentence-became-part-of-engine
            the-cake-is-a-lie))

(fact there-will-be-cake "there will be cake")

(derive accounting-for-a-lie
    (c.count-exists 
        the-next-sentence-is-grounded-in-parseltongue
        sentence-became-part-of-engine
        the-cake-is-a-lie
        there-will-be-cake) 
    :using (c.count-exists 
            the-next-sentence-is-grounded-in-parseltongue 
            sentence-became-part-of-engine
            the-cake-is-a-lie
            there-will-be-cake))

(derive count-non-lie-so-far
    (c.count-exists 
        the-next-sentence-is-grounded-in-parseltongue
        sentence-became-part-of-engine
        the-cake-is-a-lie
        (quote parseltongue)) 
    :using (c.count-exists 
            the-next-sentence-is-grounded-in-parseltongue 
            sentence-became-part-of-engine
            the-cake-is-a-lie
            parseltongue))

```
This feature of Parseltongue - catching the propagation of taints - is core to its ability to highlight hallucinations in LLM outputs.

## What Parseltongue Does

So what is it exactly? [[term:parseltongue]] is [[fact:what-is-parseltongue]]. There are [[fact:node-kinds]] primary kinds of knowledge nodes:

- A **term** is a named value - like [[term:parseltongue]] itself, defined in the very first block. Terms give names to things so the system can reference them.
- A **fact** is a claim with cited evidence - a quote from a real document that grounds it.
- A **derivation** is a computation over other nodes - like the count we calculated above.
- An **axiom** is a rule about how other things relate to each other.

This document you're reading is written in **[[term:pgmd]]** - [[fact:what-is-pgmd]]. It was designed to be a human interface with **[[term:pltg]]** - [[fact:what-is-pltg]][[~term:parseltongue]]

```scheme
;; pltg Observing the Garden
(defterm pgmd ".pgmd"  
    :evidence (evidence "self"
    :quotes ("This document you're reading is written in **[[pgmd]]** ")
    :explanation "PGMD introduction"))

(defterm pltg ".pltg"  
    :evidence (evidence "self"
    :quotes ("This document you're reading is written in **[[pgmd]]** ")
    :explanation "PLTG introduction"))

(fact what-is-parseltongue "a formal language for knowledge representation"
  :evidence (evidence "self"
    :quotes ("Parseltongue is a formal language for knowledge representation")
    :explanation "Core definition - not typed inline, resolved from here"))

(fact what-is-pgmd "a format that wires parseltongue blocks through ordinary prose"
  :evidence (evidence "self"
    :quotes ("pgmd, a format that wires parseltongue blocks through ordinary prose")
    :explanation "The format this document is written in"))

(fact what-is-pltg "the language of the Parseltongue systems themselves"
  :evidence (evidence "self"
    :quotes ("[[term:pltg]]** - [[fact:what-is-pltg]]")
    :explanation "The format the code blocks use"))

(fact verbosity-is-a-feature "verbosity is a feature"
  :evidence (evidence "self"
    :quotes ("[[term:pltg]] is quite verbose compared to typical programming languages")
    :explanation "The verbosity comment"))

(fact llm-use-design "designed to use with the LLMs"
  :evidence (evidence "self"
    :quotes ("[[term:pltg]]  is quite verbose" "writing [[term:pltg]] modules and documenting things in a somewhat redundant manner is not a problem, and readability")
    :explanation "The verbosity comment"))

(fact node-kinds 4
  :evidence (evidence "self"
    :quotes ("A **term**" "A **fact**" "A **derivation**" "An **axiom**")
    :explanation "The four primary node kinds"))


(derive count-facts-garden-block     
    (c.count-exists 
        (quote pgmd)
        (quote pltg)
        what-is-parseltongue 
        what-is-pgmd 
        what-is-pltg
        verbosity-is-a-feature
        llm-use-design
        node-kinds) 
    :using (c.count-exists 
        pgmd
        pltg
        what-is-parseltongue 
        what-is-pgmd 
        what-is-pltg
        verbosity-is-a-feature
        llm-use-design
        node-kinds))
```

Notice how the values in the previous paragraph weren't typed - they were resolved from the block above. The system knows where each one came from, what quote grounds it, and whether that quote still exists in the source. If I change the quote - the reference breaks, and you see it.

[[term:pltg]] is quite verbose compared to typical programming languages, and that [[fact:verbosity-is-a-feature]]. It lets us trace facts and relationships with very high precision. [[term:parseltongue]] was [[fact:llm-use-design]] - for them, writing [[term:pltg]] modules and documenting things in a somewhat redundant manner is not a problem, and readability is handled by [[term:pgmd]].


## Seeing It

> The answer is out there. It's looking for you and it will find you, if you want it to.

When this document is rendered, it produces [[fact:views-share-data]]:

- **Notebook** - the prose you're reading, with footnote markers linking to nodes
- **Cards** - one card per node, showing kind, value, and verification status
- **Layers** - computation-based layout: it shows the path from the core axioms used everywhere to final consequences through each derivation step
- **Graph** - the full dependency network, interactive, with taint propagation visible

```scheme
;; pltg Knowing Good and Evil

(load-document "atoms" "../../../atoms.py")
(load-document "engine" "../../../engine.py")

(defterm silence "SILENCE"
    :evidence (evidence "atoms"
    :quotes ("Silence is its own instance")
    :explanation "Silence is fundamental to Parseltongue much like other types"))



(defterm consistency "Consistent"
    :evidence (evidence "engine"
    :quotes ("def consistency(self, suppress_log: bool = True) -> ConsistencyReport: ...")
    :explanation "Consistency is calculated"))

(defterm grounding "Grounded"
    :evidence (evidence "atoms"
    :quotes ("def is_grounded(self) -> bool:" "return self.verified or self.verify_manual")
    :explanation "Grounding is checked"))



(defterm taints "Tainted"
    :evidence (evidence "engine"
    :quotes ("Types of consistency issues (errors — break consistent=True)." "UNVERIFIED_EVIDENCE = " "NO_EVIDENCE = " "POTENTIAL_FABRICATION =" "DIFF_DIVERGENCE = " "DIFF_VALUE_DIVERGENCE = ")
    :explanation "Taints are issues"))



(defterm derivations "Derived"
    :evidence (evidence "atoms"
    :quotes ("derivation: list = field(default_factory=list)" "@dataclass(frozen=True)
class Theorem:
")
    :explanation "Derivations are preserved"))

(fact view-count 4
  :evidence (evidence "self"
    :quotes ("Notebook" "Cards" "Layers" "Graph")
    :explanation "Four rendering perspectives"))

(fact views-share-data "four views of the same underlying structure"
  :evidence (evidence "self"
    :quotes ("four views of the same underlying structure")
    :explanation "Views are perspectives, not separate systems"))

(derive count-facts-knowing-block     
    (c.count-exists 
     view-count
     views-share-data
     (quote silence)
     (quote consistency)
     (quote grounding)
     (quote taints)
     (quote derivations)
     ) 
    :using (c.count-exists 
        view-count
        views-share-data
        silence
        consistency
        grounding
        taints
        derivations))

```

Those [[fact:view-count]] views ensure the transparency of the structure. They are different perspectives designed to show how conclusions were reached. The Graph makes it visible what depends on what. The Layers show how results were derived. The Cards and Sources show what was available. The Notebook shows what was reported.

This doesn't mean the notebook contains truth or lies in the body of text - the text is still just human text. The difference is that prose sentences can refer to Parseltongue sentences - which are designed to explicitly show whether they are [[term:grounding]], [[term:consistency]], and honestly [[term:derivations]]. Otherwise, the sentence will show its [[term:taints]] or return [[term:silence]].

Since all knowledge in [[term:parseltongue]] is explicit, we can check whether it follows the rules we might like it to follow:

```scheme
;; pltg Promises and Deception

(defterm concepts-not-more 25
  :origin "Our expected concepts limit")

(defterm expect-concepts 23
  :origin "Our expected concepts so far")


(axiom intro-is-substantial-but-focused (< ?n concepts-not-more)
  :origin "An introduction should not overwhelm - fewer than 20 concepts")

(verify-manual (quote intro-is-substantial-but-focused) "V")
(verify-manual (quote expect-concepts) "V")
(verify-manual (quote concepts-not-more) "V")

(fact readme-expected-focused true
  :evidence (evidence "self"
    :quotes ("For now this intro stays focused[[~term:focus-check]]")
    :explanation "We are expecting focused readme"))

(defterm diff-ops "Diff"
    :evidence (evidence "self"
    :quotes ("(diff readme-expectations replace: focus-check with: readme-expected-focused)")
    :explanation "We are expecting focused readme"))

(derive this-block-sum (c.count-exists readme-expected-focused (quote diff-ops) (quote concepts-not-more) (quote expect-concepts))
  :using (c.count-exists readme-expected-focused diff-ops concepts-not-more expect-concepts))



(derive facts-and-terms-so-far (c.sum-values count-facts-knowing-block count-facts-garden-block count-non-lie-so-far this-block-sum)
  :using (c.sum-values  count-facts-knowing-block count-facts-garden-block count-non-lie-so-far this-block-sum))

(derive focus-check intro-is-substantial-but-focused 
  :bind ((?n facts-and-terms-so-far))
  :using (facts-and-terms-so-far intro-is-substantial-but-focused))

(diff readme-counts :replace facts-and-terms-so-far :with expect-concepts)
(diff readme-expectations :replace focus-check :with readme-expected-focused)
(diff ungrounded-expectations :replace concepts-not-more :with facts-and-terms-so-far)

```

The block above computes that we have introduced [[term:facts-and-terms-so-far]] concepts so far. We could set a goal for a focused intro - say, no more than [[term:concepts-not-more]] concepts. For now this intro stays focused[[~term:focus-check]]. This is the result of evaluating our rule: [[axiom:intro-is-substantial-but-focused]]. The code after this check uses the [[term:diff-ops]] operation. If this document grew too sprawling, the coherence[[~diff:readme-expectations]] check would fail, much like our main [[diff:readme-counts]] expectation. If the promise is inaccurate - say we try to replace the concept limit with the actual count - the diff will show it: [[diff:ungrounded-expectations]]

## The Construct

> This will feel a little weird.


This document is part of **Construct** - the place where both agents and humans learn [[term:parseltongue]]. It has two modes, mirrored:

- **Scripts** - agent instructions. An LLM loads a script and gains operational knowledge - these are available in the repository and via the provided CLI with `pg learn ..topic..`, e.g. `pg learn kung-fu`
- **Scenarios** - human side. They focus on building understanding of what [[term:parseltongue]] is, and how to work with it and keep LLM agents accountable during collaborative sessions

Construct contains progressive explanations of the system context - we don't want you thrown down the rabbit hole straight into our Mad Tea Party. Instead we recommend a progressive dive with your favourite LLM assistant.

| Name | Description | Script | Scenario |
|------|-------------|--------|----------|
| white-rabbit | Introduction - what Parseltongue is and why it exists | [[fact:script-white-rabbit]] | [[fact:scenario-white-rabbit]] |
| kung-fu | Bench mastery - inspection, search, lens, diagnosis | [[fact:script-kung-fu]] | [[fact:scenario-kung-fu]] |
| to-connect | pgmd notebooks - prose wired through with truth | [[fact:script-to-connect]] | [[fact:scenario-to-connect]] |
| dodge-bullets | Screening, diagnostics, consistency | [[fact:script-dodge-bullets]] | [[fact:scenario-dodge-bullets]] |
| jump-program | Resolving dynamic refs, building consistent graphs | [[fact:script-jump-program]] | [[fact:scenario-jump-program]] |
| no-spoon-bending | Effects, verify_manual, bending accepted terms | [[fact:script-no-spoon-bending]] | [[fact:scenario-no-spoon-bending]] |
| read-the-code | Grounding layer - documents and data to facts and axioms | [[fact:script-read-the-code]] | [[fact:scenario-read-the-code]] |
| about-matrix | Systems, composition, fundamental lang | [[fact:script-about-matrix]] | [[fact:scenario-about-matrix]] |
| the-truth | Epistemics, std lib, grounding module, diffs | [[fact:script-the-truth]] | [[fact:scenario-the-truth]] |
| to-exit | Scoping, projection, delegates | [[fact:script-to-exit]] | [[fact:scenario-to-exit]] |
| to-fly | Graph navigation, search, cross-navigation | [[fact:script-to-fly]] | [[fact:scenario-to-fly]] |

[[derive:scripts-ready]] scripts and [[derive:scenarios-ready]] scenario are live. Right now the agents can already learn kung-fu and how to-connect it to [[term:pgmd]] notebooks. The explanation for you about how to steer them is WIP.

So, if you haven't yet, tell your agent to:

```bash
pip install parseltongue-dsl
pg learn kung-fu
pg learn to-connect
```

And enjoy the show of an LLM bumping into Parseltongue guardrails. **You'd be surprised how illusory intelligence becomes once it needs to be proven explicitly.**

```scheme
;; pltg Grounding

(load-document "construct" "../__init__.py")

(defterm ready (quote "✓ ready")
  :evidence (evidence "construct"
    :quotes ("\"kung-fu\": {" "\"description\": \"Bench mastery")
    :explanation "Entry in TOPICS with a discovered script/scenario file means published"))

(defterm todo (quote "-")
  :evidence (evidence "construct"
    :quotes ("\"dodge-bullets\": {" "\"description\": \"Screening, diagnostics, consistency\"")
    :explanation "Entry in TOPICS with no script or scenario file discovered"))

;; white-rabbit
(fact script-white-rabbit todo
  :evidence (evidence "construct"
    :quotes ("\"white-rabbit\": {")
    :explanation "No white-rabbit script file in scripts/"))
(fact scenario-white-rabbit ready
  :evidence (evidence "construct"
    :quotes ("\"white-rabbit\": {" "\"description\": \"Introduction")
    :explanation "This document — discovered as INTRO_WHITE-RABBIT.pg.md"))

;; kung-fu
(fact script-kung-fu ready
  :evidence (evidence "construct"
    :quotes ("\"kung-fu\": {" "\"description\": \"Bench mastery")
    :explanation "Discovered from PG-SKILL_KUNG-FU.md via alias frontmatter"))
(fact scenario-kung-fu todo
  :evidence (evidence "construct"
    :quotes ("\"kung-fu\": {")
    :explanation "No scenario file in scenarios/"))

;; to-connect
(fact script-to-connect ready
  :evidence (evidence "construct"
    :quotes ("\"to-connect\": {" "\"description\": \"pgmd notebooks")
    :explanation "Discovered from PGMD-SKILL_TO-CONNECT.md via name frontmatter"))
(fact scenario-to-connect todo
  :evidence (evidence "construct"
    :quotes ("\"to-connect\": {")
    :explanation "No scenario file in scenarios/"))

;; dodge-bullets
(fact script-dodge-bullets todo
  :evidence (evidence "construct"
    :quotes ("\"dodge-bullets\": {")
    :explanation "No script file in scripts/"))
(fact scenario-dodge-bullets todo
  :evidence (evidence "construct"
    :quotes ("\"dodge-bullets\": {")
    :explanation "No scenario file in scenarios/"))

;; jump-program
(fact script-jump-program todo
  :evidence (evidence "construct"
    :quotes ("\"jump-program\": {")
    :explanation "No script file in scripts/"))
(fact scenario-jump-program todo
  :evidence (evidence "construct"
    :quotes ("\"jump-program\": {")
    :explanation "No scenario file in scenarios/"))

;; no-spoon-bending
(fact script-no-spoon-bending todo
  :evidence (evidence "construct"
    :quotes ("\"no-spoon-bending\": {")
    :explanation "No script file in scripts/"))
(fact scenario-no-spoon-bending todo
  :evidence (evidence "construct"
    :quotes ("\"no-spoon-bending\": {")
    :explanation "No scenario file in scenarios/"))

;; read-the-code
(fact script-read-the-code todo
  :evidence (evidence "construct"
    :quotes ("\"read-the-code\": {")
    :explanation "No script file in scripts/"))
(fact scenario-read-the-code todo
  :evidence (evidence "construct"
    :quotes ("\"read-the-code\": {")
    :explanation "No scenario file in scenarios/"))

;; about-matrix
(fact script-about-matrix todo
  :evidence (evidence "construct"
    :quotes ("\"about-matrix\": {")
    :explanation "No script file in scripts/"))
(fact scenario-about-matrix todo
  :evidence (evidence "construct"
    :quotes ("\"about-matrix\": {")
    :explanation "No scenario file in scenarios/"))

;; the-truth
(fact script-the-truth todo
  :evidence (evidence "construct"
    :quotes ("\"the-truth\": {")
    :explanation "No script file in scripts/"))
(fact scenario-the-truth todo
  :evidence (evidence "construct"
    :quotes ("\"the-truth\": {")
    :explanation "No scenario file in scenarios/"))

;; to-exit
(fact script-to-exit todo
  :evidence (evidence "construct"
    :quotes ("\"to-exit\": {")
    :explanation "No script file in scripts/"))
(fact scenario-to-exit todo
  :evidence (evidence "construct"
    :quotes ("\"to-exit\": {")
    :explanation "No scenario file in scenarios/"))

;; to-fly
(fact script-to-fly todo
  :evidence (evidence "construct"
    :quotes ("\"to-fly\": {")
    :explanation "No script file in scripts/"))
(fact scenario-to-fly todo
  :evidence (evidence "construct"
    :quotes ("\"to-fly\": {")
    :explanation "No scenario file in scenarios/"))

(derive scripts-ready (c.count-exists script-kung-fu script-to-connect)
  :using (c.count-exists script-kung-fu script-to-connect))

(derive scenarios-ready (c.count-exists scenario-white-rabbit)
  :using (c.count-exists scenario-white-rabbit))
```


---

## What's Next

> we're all mad here

Unfortunately, there are many more kinds of deception than outright lies, incoherent statements, or ungrounded hallucinations. Agents can still stretch perfectly grounded facts, provide incomplete answers, or hide the truth in other ways - not intentionally, but simply because they don't know how not to.

As with any language, using [[term:parseltongue]] accurately requires mastery. And mastery comes from deeper understanding.

Understanding follows curiosity, and if - unlike Alice - you haven't yet followed the trails leading into the web of [[term:parseltongue]]'s Wonderland, I highly recommend you pursue that option.

Here are two statements: the [[diff:readme-expectations]] readme expectations check, and the alternate reality [[diff:ungrounded-expectations]] of the ungrounded diff. Take any pill - this is your fairly classical choice, and understanding why the red one is red leads much deeper.

But if you want to join the Mad Tea Party without being constrained by binary choices, we have another pill:

[[diff:readme-counts]]

And the most interesting question in this notebook is: "Why is it yellow?"