# Provider integrations

Verified against public documentation on **20 October 2026**. No live credentialed calls were made from this workspace, so request construction is verified from the docs and unit tests, not from a successful provider account.

## YouCam

Account and keys: [YouCam API console](https://yce.makeupar.com/api-console/en/api-keys/)

Base URL used by the adapter: `https://yce-api-01.makeupar.com`

Authentication on every API call: `Authorization: Bearer <YOUCAM_API_KEY>`

### File upload

Documented in the quick start and in each feature guide.

- Create upload: `POST /s2s/v2.0/file`
- Body: `files[].content_type`, `file_name`, `file_size`
- Response: `data.files[].file_id` and `data.files[].requests[]` with `method`, `url`, and `headers`
- The file bytes are then sent to `requests[].url` with the returned method and headers. Calling the file endpoint alone does not upload the image.
- JPEG uploads use the documented content type `image/jpg`. WebP uploads are converted to JPEG first because the try-on pages list JPEG and PNG.

References:

- [Quick start](https://docs.perfectcorp.com/develop/quick_start_guide)
- [File API example](https://docs.perfectcorp.com/reference/ai_skin_analysis/section/overview/integration-guide)

Default input mode is `file_upload`, so local development does not need a public image host. `YOUCAM_INPUT_MODE=public_url` sends `src_file_url` and `ref_file_url` instead, and those URLs must be reachable by YouCam.

### Clothes

Current documented operation is AI Cloth V4, which adds outerwear.

- Create: `POST /s2s/v2.0/task/cloth-v4`
- Poll: `GET /s2s/v2.0/task/cloth-v4/{task_id}`
- `garment_category`: `full_body`, `lower_body`, `upper_body`, `shoes`, `auto`, `outer`
- `change_shoes` applies when the category is `full_body` or `lower_body`. FrameFit sends `false` unless the person turns the option on.
- `filter_multi_person`: `off`, `normal`, `strict`. Default `off`.

FrameFit internal categories map to provider values as:

| Internal | Provider `garment_category` |
| --- | --- |
| upper_body | upper_body |
| lower_body | lower_body |
| full_body | full_body |
| outerwear | outer |

Shoe try-on does not use this endpoint. It uses the shoes adapter below.

References:

- [AI Clothes V4](https://docs.perfectcorp.com/reference/ai_clothes/v4.0)
- [Create cloth V4 task](https://docs.perfectcorp.com/reference/ai_clothes/v4.0/paths/~1s2s~1v2.0~1task~1cloth-v4/post)
- [Cloth V4 status](https://docs.perfectcorp.com/reference/ai_clothes/v4.0/paths/~1s2s~1v2.0~1task~1cloth-v4~1%7Btask_id%7D/get)
- [Clothes file specs](https://docs.perfectcorp.com/reference/ai_clothes/section/overview/file-specs-and-errors)

Documented clothes limits used by the adapter: JPEG or PNG, under 10 MB, long side at most 4096, minimum about 512×384. Smaller crops are padded onto a plain background and that preparation is stored in the version settings.

### Hat

- Create: `POST /s2s/v2.0/task/hat`
- Poll: `GET /s2s/v2.0/task/hat/{task_id}`
- Required `gender`: `female` or `male`
- `style` controls the outfit and background, not the hat by itself. Values: `random`, `style_sporty_casual`, `style_urban_fashion`, `style_vacation_casual`, `style_warm_cozy`, `style_bohemian`. `random` lets the service pick one of those looks.
- The default hat try-on omits `style` and pastes only the headwear from the result back onto the original photo. The person can turn that off to keep the full restyled portrait.
- Source and reference: file id or public URL

References:

- [AI Hat](https://docs.perfectcorp.com/reference/ai_hat)
- [Create hat task](https://docs.perfectcorp.com/reference/ai_hat/v2.0/paths/~1s2s~1v2.0~1task~1hat/post)

Documented minimums: 512×512, long side at most 4096, under 10 MB, JPEG/PNG. The overview also says the face should be visible.

### Scarf

- Create: `POST /s2s/v2.0/task/scarf`
- Poll: `GET /s2s/v2.0/task/scarf/{task_id}`
- Required `gender`: `female` or `male`
- `style`: `random`, `style_french_elegance`, `style_light_luxury`, `style_cottagecore`, `style_modern_chic`, `style_bohemian`

References:

- [AI Scarf](https://docs.perfectcorp.com/reference/ai_scarf)
- [Create scarf task](https://docs.perfectcorp.com/reference/ai_scarf/v2.0/paths/~1s2s~1v2.0~1task~1scarf/post)

The scarf overview describes the same file-upload flow. A separate numeric minimum resolution was not quoted on the pages fetched here, so the adapter uses the shared documented limits of JPEG/PNG, under 10 MB, and long side at most 4096, and pads very small crops to 512×512.

### Shoes

The integration guide and V3 reference use `POST /s2s/v2.0/task/shoes-transfer`.

- Create: `POST /s2s/v2.0/task/shoes-transfer`
- Poll: `GET /s2s/v2.0/task/shoes-transfer/{task_id}`
- The V3 request schema and example send only the source and reference file URL or file id. They do not list `gender` or `style`.

An older shoes page, `POST /s2s/v2.0/task/shoes`, does list gender and style. The integration guide curl for `shoes-transfer` also shows gender and style, while the V3 schema does not. The adapter follows the V3 schema and does not send gender or style. If a live key rejects that body, this is the first thing to re-check. It is not silently replaced with another API.

References:

- [AI Shoes](https://docs.perfectcorp.com/reference/ai_shoes)
- [Shoes V3 create task](https://docs.perfectcorp.com/reference/ai_shoes/v3.0/paths/~1s2s~1v2.0~1task~1shoes-transfer/post)

Documented shoe image notes from the overview: minimum 512×512, long side at most 4096, under 10 MB, feet visible on the person photo.

### Bag

- Create: `POST /s2s/v2.0/task/bag`
- Poll: `GET /s2s/v2.0/task/bag/{task_id}`
- Required `gender`: `female` or `male`
- `style`: `random`, `style_parisian_chic`, `style_urban_chic`, `style_mediterranean_chic`, `style_art_deco_style`
- Source and reference: file id or public URL. The same File API upload used by the other try-on tasks applies. This is not the skin-analysis task.

References:

- [AI Bag](https://docs.perfectcorp.com/reference/ai_bag)
- [Create bag task](https://docs.perfectcorp.com/reference/ai_bag/v2.0/paths/~1s2s~1v2.0~1task~1bag/post)

The bag overview asks for a selfie with the face visible, at least a head-to-chest view, and a bag image of at least 512×512. The adapter pads small crops to 512×512.

In `mixed` and `real` mode, a configured key sends hat, clothes, shoes, scarf, and bag to these task paths. A failed task is not replaced with a demo image.

### Task results

Successful task reads in the feature guides look like:

```json
{
  "status": 200,
  "data": {
    "task_status": "success",
    "results": { "url": "https://..." },
    "error": null
  }
}
```

The status reference also describes a result `url` that is valid for about two hours. FrameFit downloads that image immediately into its own storage. `task_status` of `error` fails the job. Other statuses are polled with backoff until the configured timeout. A failed or missing key never falls back to a demo image.

## SerpApi Google Lens

References:

- [Google Lens API](https://serpapi.com/google-lens-api)
- [Visual matches](https://serpapi.com/google-lens-visual-matches-api)
- [Image upload](https://serpapi.com/image-api)
- [Lens by uploaded image](https://serpapi.com/google-lens-upload-an-image)

Flow:

1. `POST https://serpapi.com/image` as multipart form data with fields `image` and `api_key`. JPEG, PNG, or WebP, maximum 500 KB. The response `image_id` expires after about 10 minutes.
2. `GET https://serpapi.com/search.json` with `engine=google_lens`, `type=visual_matches`, `image_id`, and optional `q` and `hl`.

FrameFit compresses the item crop under 500 KB, uploads it, and reads `visual_matches`. Prices are copied only when `price.extracted_value` is present. Links that are not safe http(s) URLs are dropped. Duplicate links are removed. Social and editorial hosts are labeled `similar_style`. `exact_matches` is stored only as a flag and is not shown as proof of the same garment.

Product images fetched afterwards must pass a public-address check, a size limit, and an image-content check. Redirects are followed manually and checked again.

## What was not verified live

- A YouCam key was not available, so no task reached `task_status: success` on YouCam's servers.
- A SerpApi key was not available, so no live Lens response was fetched.
- YOLOWorld weights were not downloaded in the test environment. Demo mode does not load the model. Real and mixed modes load `yolov8s-worldv2.pt` once at startup when the Ultralytics package is installed.
