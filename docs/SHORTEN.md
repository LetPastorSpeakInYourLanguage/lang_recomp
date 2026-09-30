# Shortening lines that cannot fit (decision 47)

**Status:** built 2026-10-01 (branch `feat/shorten`); first real run on Colab pending.
Code: `app/translate/fit.py` (the verdict), `worker/lb_worker/llm.py` (the model server),
`worker/lb_worker/shorten.py` (the loop), `translation_options` (the stored versions),
Translate screen (the meter and the chooser). Notebook setting `SHORTEN_WITH_LLM` (on by default).

## Why: measured on our own lines (2026-09-30)

669 Amharic lines in the owner's library (656 from Google), and the voice-path test on the camille clip
(`spikes/voice_paths`):

| | Camille interview | 6 Minute English (7 episodes) |
|---|---|---|
| Amharic syllables ÷ English syllables (median) | 1.43 | 1.76–2.00 |
| English speaking rate (syllables/s) | 3.7 | 4.3–4.8 |
| Chosen take ÷ English slot (old clone voice at 1.4×) | 1.10 | 1.34–1.59 |

- **The native voice (decision 46) speaks at ~6.0 syllables/s** (native OmniVoice 6.02, edge-tts
  5.99), against 5.24 for the English-prompted clone at 1.4×. Its lengths can be predicted from
  the text: actual take length ÷ (syllables / 6.0) has a median of 1.00 and a 90th percentile of 1.22. Seed-VC keeps the timing.
- **Cropping pauses gains little**: squeezing the voice prompt's pauses cut total length by 2 %
  (101.6 → 99.5 s) and raised the error rate (median 0.125 → 0.19).
- **Pooling time across neighbouring lines of the same speaker gains nothing**. Nearly every line on
  6 Minute English is over, so moving time or words between neighbours only moves the overflow.
  Needed speed-up with the pause around each line: median 1.19×. Pooled across same-speaker
  lines: 1.30×.
- So **the text has to get shorter**. With the native voice, the share of **tight** lines is
  43 % on 6 Minute English and 3 % on Camille. The median cut needed to fit freely is 22 %.

## The rule

A line's **window** runs from its start (or up to 0.3 s earlier, never before the previous line
ends + 0.08 s) to the next line's start − 0.08 s, with neighbours at their source times.
**need** = predicted spoken length / window. It is **tight** when even the mix's hardest squeeze
(1.25×) cannot fit it without overlapping a neighbour (owner, 2026-09-30).

## The loop (only tight lines; English side only for now)

1. After Google has translated the run, collect the tight lines. People's wording, locked lines,
   lines kept in the original voice and recurring parts are skipped.
2. **Gemma 4 E4B** (Google's QAT Q4_0 GGUF, 4.9 GB, Apache 2.0; E2B without a GPU) on
   **llama.cpp's prebuilt server** (release b11298), with 4 parallel slots and JSON-schema answers.
   - It writes two shorter English versions per line: `a` ≤ words × 1.10 / need, `b` ≤ words × 0.90 / need.
   - Up to 8 lines per request, with 2 lines of context each side and the chapter title.
   - The English is written once for all target languages.
3. Google translates both versions. Each is measured in the window, and its meaning is checked:
   original vs shortened English, `all-mpnet-base-v2` on the CPU, loaded while the model writes.
4. The choice: the most faithful version that fits freely (need ≤ 1.12, meaning ≥ 0.75); else the
   shortest faithful one ≤ 1.25; else Google's own. All versions are stored and shown in the
   Translate screen; **Use** makes one the person's wording.
5. `runs/<run>/shorten.json` reports tight / fits / closer / too long / time / tokens per second.
   A restarted run skips lines already done. If the model cannot run, Google's translations stay.

Why this route: vLLM on a T4 needs patches for its memory limits, a 6-minute start and a pinned
torch, while llama.cpp's server is a 163 MB download that leaves the session's packages alone.
Small models write English far better than Amharic, and Google keeps its Amharic quality.

## Open (BACKLOG)

- First Colab run (about 3 episodes of 6 Minute English, SHORTEN on and off): tokens/s, overflow before and after, a listen;
  set `MIN_SIM` from the spread of meaning scores.
- Shortening the translation itself (target side) for chosen languages. Amharic stays off until
  the E3 bench shows Gemma writes it well.
- A rescue pass after voicing, for lines whose real take still overflows.
- LLM chapters (SCALE M4a): a pass on sentence embeddings + pauses proposes boundaries, the model
  adjusts them by line number and writes titles, summaries and key terms (the Chapter-Llama method).
