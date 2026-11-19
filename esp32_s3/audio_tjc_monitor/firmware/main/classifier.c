/* PetLink 板端分类器（C89 兼容）——B 组验收矩阵 B09/B10 的 C 侧实现。
 *
 * 数学契约（与 petlink.training 训练管线逐参数一致）：
 *   1) NaN 特征 → 该模型导出的 median 插补
 *   2) x' = (x - mean) / scale   （scale 为 0 时按 1 处理——导出器已校验 scale>0）
 *   3) logit = coef · x' + bias  （二分类单 logit，sigmoid 概率，classes_[1] 为正类）
 * 三模型（coarse / positive_fine / negative_fine）各自持有独立 median/mean/scale，禁止共用。
 */
#include <math.h>
#include "classifier.h"

static float cat_sigmoid(float z) {
    if (z > 30.0f) return 1.0f;
    if (z < -30.0f) return 0.0f;
    return 1.0f / (1.0f + expf(-z));
}

/* 单模型推理：features[CAT_FEATURE_COUNT] -> P(classes_[1])。返回 logit 便于调试。 */
float cat_model_probability(const float *features, int model_index, float *logit_out) {
    static const float *const per_model_median[CAT_MODEL_COUNT] = {coarse_median, positive_fine_median, negative_fine_median};
    static const float *const per_model_mean[CAT_MODEL_COUNT] = {coarse_mean, positive_fine_mean, negative_fine_mean};
    static const float *const per_model_scale[CAT_MODEL_COUNT] = {coarse_scale, positive_fine_scale, negative_fine_scale};
    static const float *const per_model_coef[CAT_MODEL_COUNT] = {coarse_weight, positive_fine_weight, negative_fine_weight};
    static const float *const per_model_bias[CAT_MODEL_COUNT] = {coarse_bias, positive_fine_bias, negative_fine_bias};
    const float *median = per_model_median[model_index];
    const float *mean = per_model_mean[model_index];
    const float *scale = per_model_scale[model_index];
    const float *coef = per_model_coef[model_index];
    const float bias = per_model_bias[model_index][0];

    float acc = bias;
    int j;
    for (j = 0; j < CAT_FEATURE_COUNT; ++j) {
        float value = features[j];
        if (isnan(value)) {
            value = median[j];
        }
        float s = scale[j];
        if (!(s > 0.0f)) {
            s = 1.0f;
        }
        acc += coef[j] * ((value - mean[j]) / s);
    }
    if (logit_out != 0) {
        *logit_out = acc;
    }
    return cat_sigmoid(acc);
}
