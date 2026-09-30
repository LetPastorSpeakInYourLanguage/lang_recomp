# Voice research: target-language speech that sounds native, in the speaker's voice

**Date:** 2026-09-30 · **Status:** research, no decision yet · Links: [DECISIONS #8](DECISIONS.md),
[PLAN Phase C](PLAN.md), [SCALE_RESEARCH §8](SCALE_RESEARCH.md)

The question: we have the speaker's voice (a character's bank, in English) and the text to
say (in Amharic, or any target). What ways are there to produce speech that sounds **native**
in the target language and still sounds **like the speaker**, and what does each one cost?

---

## 1. What we do today, and why it sounds a little foreign

- Engine: **OmniVoice** (`k2-fsa/OmniVoice`), a masked-diffusion language model (Qwen3-0.6B
  backbone, HiggsAudio codec). One generate call per line; the **character's English bank**
  (12–20 s today) is the voice prompt; 16 steps, speed 1.4×, 2 takes, scored by likeness
  (WavLM), back-transcription CER (Ethio-ASR) and fit (`worker/lb_worker/stages/voice.py`,
  `tts/omnivoice_gen.py`, `tts/score.py`).
- This is **in-context cloning**: the model continues the prompt. It has no separate "timbre"
  and "prosody" inputs, unlike StyleTTS2, which has an acoustic-style and a prosodic-style
  encoder. Whatever the prompt carries (timbre, English rhythm, English intonation, English
  accent) carries on into the Amharic.
- OmniVoice's README says so itself: with a reference in another language, *"the generated
  speech will carry an accent from the reference audio's language"*.
- Things we control that make it worse:
  - **Long English prompts**: 12–20 s, where OmniVoice advises 3–10 s. That is more English
    rhythm for the model to continue.
  - **1.4× speed**: Amharic needs more syllables than the English slot, and fast speech sounds
    less natural whatever the engine. The translation "Fit" step (SCALE 7) is the real fix.
  - **Each line on its own**: there is no sentence-to-sentence flow.
- Measured (bake-off, STATE.md): OmniVoice + bank 0.89 likeness / 10.5 % CER; the Amharic
  fine-tune 0.88 / 9.4 %; edge-tts 0.66 / 12.4 %. **Seed-VC (edge → speaker) never finished
  a run**, so the "native base + conversion" path has **never been measured**. Nothing in the
  scorer measures how native a take sounds.

## 2. Hasab AI and Addis AI: what they most plausibly do

I can't listen to audio, so this rests on their docs, API shapes, released data and
benchmark, not on listening.

### Addis AI (addisassistant.com, "Addis Voices 2", models አሌፍ-Audio-AM / -OM)

| Evidence | What it says |
|---|---|
| 28 voices, **19 Amharic-only + 9 Oromo-only**; none speaks both languages | The voices come from each language's training speakers, not from a converter (a converter would let any voice speak any supported language) |
| Voice Lab: Speed / Stability / Similarity / Style Exaggeration; formats `mp3_44100`, `wav_44100`, `pcm_16000` | An ElevenLabs-shaped API. The docs: stability, similarity and style *"are accepted for compatibility but ignored by the current provider"*; only speed is applied |
| Benchmark lists the model as *"production standard checkpoint"*; compare page: *"TTS, STT and the LLM are our own models"* | Their own trained model, not a resold one |
| v2 *"does not stream partial audio"* (the legacy engine did stream); median latency 5.4 s | Fits a non-autoregressive model that makes the whole clip at once (flow-matching or masked-diffusion, the F5-TTS / OmniVoice family) |
| Founder's HF datasets: `wxl_amh`, `waxal-orm-tts-merged` (WAXAL **ASR** split + auto-labelled, 100K+ rows, many speakers), `afaan-oromo-tts` (`speaker_id`, `gender`) | Trained on large many-speaker native data, which is data for a prompt- or speaker-conditioned model, not for a few-voice VC model |
| "My Voices" tab present but inactive; no clone endpoint in the page code | Cloning is not offered yet (the tab suggests it may come) |
| Their benchmark (12 Aug 2026, 100 prompts, blind): naturalness Addis **4.01**, Gemini 3.1 Flash TTS 3.90, Meta MMS 3.09, Azure Ameha 2.54 (**= edge-tts's voice**), gpt-4o-mini-tts 1.20, ElevenLabs v3 1.00 | Native-trained models win on naturalness; Azure/Gemini win on ASR error. The data is public: `addisai/amharic-tts-benchmark` (800 clips + human references + judge rows) |

**Most plausible:** a modern zero-shot TTS, fine-tuned or trained on WAXAL plus their own
Amharic/Oromo data, used with a **fixed catalogue of native-speaker voice prompts** (or speaker
ids) that they curated and labelled ("Immersive suspenseful storytelling" …). Their voices
sound native because **the voice prompt is a native speaker speaking the language**. Their
naturalness does not come from a conversion stage.

### Hasab AI (hasab.ai)

- 6 Amharic voices (Selam, Aster, Hanna, Yared, Haile, Tigist) and **1 Oromo voice**
  (Lemlem); the API takes `speaker_name` only; streaming, 8–48 kHz.
- Feature page: *"language-specific speaker models"* and *"Reference-Based Speech Synthesis:
  clone or adapt voices by providing reference audio"*. The public API does not expose the
  reference option.
- Most plausible: per-language multi-speaker models, one voice per recorded speaker (Oromo had
  one speaker, so it has one voice), with cloning offered separately or internally. If there
  were a VC stage, the six Amharic timbres would be available for Oromo at no cost.
- Side find: Hasab released **`hasab-ai/YehaTranslate`**, a TranslateGemma-4B fine-tune for
  am/ti/om. It belongs in the E3 translation bench.

### About the StarGANv2-VC idea

It is unlikely for either product. The voice counts differ per language and no voice crosses
languages; StarGANv2-VC only converts between the fixed speakers it was trained on; and
2021-era VC would not beat Gemini on blind naturalness. The **"native speech, then convert
the timbre"** idea is still a good one for us, done with today's zero-shot VC (option B below).

## 3. The options

"Nativeness" = sounds like a native speaker of the target language (rhythm, intonation,
consonants). "Likeness" = sounds like the source speaker.

| # | Method | How | Nativeness | Likeness | Effort / cost | Notes |
|---|---|---|---|---|---|---|
| A | **Direct cross-lingual cloning** (today) | OmniVoice + English bank | ◑ (English accent carries over, documented) | ● (0.89) | done | One model, any language. Cheap fixes: 3–10 s prompts (E4), less speed-up, pick takes by nativeness |
| A2 | Same, **Amharic fine-tuned** model | `african-low-resource/omnivoice-amharic` (331 h: WAXAL 200 h + 3 sets) | ◑+ (stronger Amharic prior, same leak) | ● (0.88) | a model name in the engine config | Already benched on numbers, never rated by ear for nativeness |
| B | **Native base → voice conversion** (cascade) | 1) Make native speech: OmniVoice(-am) with a **native Amharic prompt** matched to the character (gender, pitch, age, by x-vector), or Addis / Gemini / a human reader. 2) Convert the timbre to the character's bank | ● (prosody is the native base's) | ◑ (VC loses some likeness, and can add artefacts) | medium: a native-prompt pool + a VC stage | VC options: **Seed-VC v1** (zero-shot, 1–30 s ref, GPL-3.0), Chatterbox S3Gen VC (MIT), OpenVoice v2 (MIT), kNN-VC (needs ~5 min of target speech; banks across episodes have that), RVC (trained per speaker, 10+ min; worth it for a recurring preacher). **Do not use Seed-VC v2 with style conversion**: it converts the accent back towards the reference (see §4) |
| C | **Native voice only, matched** | Pick the nearest native voice (gender/pitch/age); no conversion | ● | ○ (gender and roughly the voice type) | low | The "edge-tts for gender" fallback, but better: edge-tts/Azure scored 2.54 naturalness vs 3.9–4.0 for Gemini/Addis. A native-prompt pool in OmniVoice-am costs nothing per minute |
| D | **Disentangled TTS**: timbre from the speaker, prosody from the language | StyleTTS2 trained multilingual **with language embeddings** (Amharic from WAXAL + English LibriTTS-R), speaker style from the English bank | ● if language embeddings work | ◑–● | high: training a model (days on a big GPU), research risk | The principled "StyleTTS2-like" answer. EACL 2026: without language embeddings the output had a strong English accent (target-language LID 0.003); with them, 0.67 (natural recordings: 0.53) |
| E | **Teach the cloner to drop the accent** | Fine-tune OmniVoice on synthetic same-speaker cross-language pairs (Cross-Lingual F5-TTS 2 method), or steer activations at inference (2026, training-free) | ●? | ● | high, research | Nothing ready for Amharic |
| F | **Human reader → conversion** (Phase C) | A native reader records the lines (teleprompter), then VC to the character's timbre | ●● (real native delivery and emotion) | ◑ | people's time | **Same VC stage as B**: build it once and Phase C `convert` gets it too |
| G | **Per-speaker adaptation** | Fine-tune an Amharic multi-speaker model on one recurring speaker's English hours, with a language token | ◑–● | ●● | medium-high per speaker | Only worth it for someone in hundreds of videos (a main preacher); accent entanglement risk, as in D |

● good · ◑ partial · ○ weak

## 4. The compromises

1. **Nativeness vs likeness is the main trade.** One prompt carries both, so a model that
   copies the voice closely also copies the accent (A, A2). Separating them costs likeness
   (B, C, F) or training (D, E, G).
2. **VC settings decide what survives.** EACL 2026 (StyleTTS2 output in nêhiyawêwin, converted
   by Seed-VC): **v1-xlsr** kept the language (LID 0.51 vs 0.53 for real speech, MOS 3.98);
   **v2** with style conversion lost it (LID 0.02–0.17). Convert **timbre only**.
3. **Cost and control.** Commercial native bases (Addis about $0.032/min, Gemini, Azure) need
   keys and have terms of service. Converting their catalogue voices into someone else's
   timbre may break those terms; check before relying on it. Open bases (OmniVoice-am with
   native prompts, MMS) run in the notebook at no per-minute cost.
4. **Licences.** Seed-VC is GPL-3.0. Run it as its own process, as the bakeoff stage already
   does; keep it out of the MIT code.
5. **Consent.** Every cloning route here reproduces a real person's voice. Phase C's consent
   rules should cover cloned characters too, not only human readers.

## 5. Recommendation

**Keep OmniVoice direct cloning as the default** (A/A2). It is the only route measured at
about 0.9 likeness. **Add "native + convert" (B) as a per-character engine option**, since it:

- goes at the nativeness problem directly;
- **is the same VC stage Phase C needs** for human readers (F);
- lets the native base be swapped freely: an OmniVoice-am native prompt, Addis, Gemini, a
  human reader.

Fall back to C (native voice matched by gender) rather than plain edge-tts; edge-tts is
Azure Ameha, which rated lowest of the native-capable systems on naturalness.

Before building it, measure. **Voice bake-off 2** on 20–30 lines × 3 characters (the
`tts_bakeoff` stage already runs each system in its own process):

| System | What it answers |
|---|---|
| S0 today's OmniVoice (English bank, 1.4×) | baseline |
| S1 OmniVoice-am, English bank | does the fine-tune alone fix it? |
| S2 OmniVoice-am with a **native Amharic prompt** matched by gender/pitch | nativeness ceiling of the engine (C) |
| S3 S2 + **Seed-VC v1** timbre → character bank | option B, open stack |
| S4 S2 + Chatterbox or OpenVoice VC | a second VC for comparison |
| S5 Addis or Gemini voice + Seed-VC v1 | option B with a commercial native base (if keys allow) |
| S6 3–6 s English prompt instead of 12–20 s | cheap fix for A (overlaps E4) |

Scores: likeness (WavLM), CER (Ethio-ASR), fit, and **a new nativeness score**, the
Amharic confidence of Meta's language-ID model (`facebook/mms-lid-126` / `-256`; both
include `amh`, `orm`, `eng`), as the EACL paper did. Calibrate that score against
**Addis's public benchmark** (800 clips across 7 systems + human references, with listener
ratings) before trusting it. Then a blind ear test by 2–3 Amharic speakers on nativeness and
likeness, like E3 for translation.

With the nativeness score in `score.py`, today's pipeline also gets better at once:
`take_score` can prefer the more native of its takes.

## Sources

Hasab: [site](https://www.hasab.ai) · [TTS feature page](https://developer.hasab.ai/features/text-to-speech) ·
[TTS API](https://developer.hasab.ai/api-integration/text-to-speech) ·
[YehaTranslate](https://huggingface.co/hasab-ai/YehaTranslate).
Addis: [Voice Lab](https://addisassistant.com/voice) ·
[TTS docs](https://docs.addisassistant.com/docs/capabilities/text-to-speech) ·
[benchmark](https://addisassistant.com/benchmarks/addis-voice-2-amharic) ·
[benchmark data](https://huggingface.co/datasets/addisai/amharic-tts-benchmark) ·
[open source](https://addisassistant.com/open-source) · [vs ElevenLabs](https://addisassistant.com/compare/elevenlabs) ·
[Telegram channel](https://t.me/s/addisassistantai) ·
[waxal-orm-tts-merged](https://huggingface.co/datasets/b1n1yam/waxal-orm-tts-merged).
Models and papers: [OmniVoice](https://github.com/k2-fsa/OmniVoice) ·
[OmniVoice Amharic](https://huggingface.co/african-low-resource/omnivoice-amharic) ·
[Seed-VC](https://github.com/Plachtaa/seed-vc) ·
[Chatterbox VC](https://github.com/LAION-AI/chatterbox-voice-conversion) ·
[WAXAL](https://arxiv.org/abs/2602.02734) ·
[Cross-lingual VC for low-resource TTS, EACL 2026](https://aclanthology.org/2026.eacl-short.16.pdf) ·
[Accent-neutralized zero-shot TTS](https://arxiv.org/abs/2603.05977) ·
[Cross-Lingual F5-TTS 2](https://arxiv.org/abs/2609.15184) ·
[IWSLT 2026 cross-lingual voice cloning track](https://iwslt.org/2026/voice-cloning) ·
[MMS-LID](https://huggingface.co/facebook/mms-lid-126).
