# Evaluation

No measurements have been recorded. Leave a cell blank until that run is observed. Do not treat an empty cell as a good result.

| Run | Date | Mode | Detection latency | Category accuracy | Missed items | Sequential preservation | Search relevance | Generation reliability | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |

Suggested notes, without invented scores:

- Detection latency: time from confirmed image to returned boxes, and whether the model was already loaded.
- Category accuracy: of the boxes a person accepted, how many prompts matched the item they meant.
- Missed items: visible garments with no box, before anyone drew one.
- Sequential preservation: see the checklist below.
- Search relevance: whether the first merchant links were about the selected crop.
- Generation reliability: completed, failed, or interrupted, and the message shown.

## Manual checklist

Use the same photo and do not delete versions between steps.

### Do later try-ons keep earlier items?

1. Try a hat on the original photo.
2. From that saved hat version, try outerwear.
3. From that result, try shoes.
4. Compare the three saved images.

Record:

- Is the hat still visible after outerwear?
- Is the hat still visible after shoes?
- Did shoes change when outerwear was applied, with "Also replace shoes" turned off?
- Did the provider message mention a failure, a missing face, or a rejected option?

This build does not claim that sequential calls preserve earlier items. The provider receives the current photo and one new reference. Whether earlier garments remain is an observed outcome, not a guarantee.

### Does replacing an item of the same category work?

1. From the original, try one jacket and save it.
2. Go back to the original with Reset look. Do not delete the first jacket.
3. Try a different jacket or coat.
4. Open History and confirm both outerwear versions still exist on separate branches.
5. Compare the two results with the original.

Record:

- Did the second jacket replace the first on that branch, or did both appear?
- Did resetting remove any saved image? It should not.
- Were the two results easy to tell apart in the history labels?

## Demo versus live

If the Demo data badge is visible, the row's mode must say demo or mixed. Do not enter those generations in the reliability column as live provider successes.
