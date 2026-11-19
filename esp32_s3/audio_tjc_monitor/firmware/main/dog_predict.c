/* PetLink 狗版分类器（C89 兼容）——猫狗合一板端的狗侧实现。
 *
 * 数学契约与 cat classifier.c 一致：
 *   1) NaN 特征 → median 插补；2) x' = (x - mean)/scale；3) logit = coef·x' + bias
 * 三模型：
 *   - species：二分类 cat/dog（1 logit，sigmoid）
 *   - gate：   二分类 dog/non_dog（1 logit，sigmoid）
 *   - state：  三分类 active/alert/rest（3 logits，softmax，argmax 无拒识）
 */
#include <math.h>
#include <string.h>
#include "dog_predict.h"

static float dog_sigmoid(float z) {
    if (z > 30.0f) return 1.0f;
    if (z < -30.0f) return 0.0f;
    return 1.0f / (1.0f + expf(-z));
}

/* 单 logit 二分类：features -> P(classes[1])，logit 可选输出。 */
static float binary_prob(const float *median, const float *mean, const float *scale,
                         const float *coef, const float *bias, const float *features, float *logit_out) {
    float acc = bias[0];
    for (int j = 0; j < DOG_FEATURE_COUNT; ++j) {
        float value = features[j];
        if (isnan(value)) value = median[j];
        float s = scale[j];
        if (!(s > 0.0f)) s = 1.0f;
        acc += coef[j] * ((value - mean[j]) / s);
    }
    if (logit_out) *logit_out = acc;
    return dog_sigmoid(acc);
}

/* 多分类 softmax：n_logits 个 logit -> n 个概率（总和 1）。 */
static void softmax_probs(const float *median, const float *mean, const float *scale,
                          const float *coef, const float *bias, int n_logits,
                          const float *features, double probs_out[]) {
    double logits[8];
    double max_logit = -1e300;
    for (int c = 0; c < n_logits; ++c) {
        double acc = bias[c];
        for (int j = 0; j < DOG_FEATURE_COUNT; ++j) {
            float value = features[j];
            if (isnan(value)) value = median[j];
            float s = scale[j];
            if (!(s > 0.0f)) s = 1.0f;
            acc += coef[c * DOG_FEATURE_COUNT + j] * ((value - mean[j]) / s);
        }
        logits[c] = acc;
        if (acc > max_logit) max_logit = acc;
    }
    double sum = 0.0;
    for (int c = 0; c < n_logits; ++c) {
        logits[c] = exp(logits[c] - max_logit);
        sum += logits[c];
    }
    for (int c = 0; c < n_logits; ++c) probs_out[c] = logits[c] / (sum > 0 ? sum : 1.0);
}

/* 物种门控：返回 0=cat, 1=dog。 */
int dog_species_classify(const float *features, float *dog_prob) {
    float p = binary_prob(species_median, species_mean, species_scale, species_weight, species_bias, features, NULL);
    if (dog_prob) *dog_prob = p;
    /* classes: [cat, dog]，sigmoid 输出 P(dog) */
    return p > 0.5f ? 1 : 0;
}

/* 狗门控：返回 0=non_dog, 1=dog。 */
int dog_gate_classify(const float *features, float *dog_prob) {
    float p_non_dog = binary_prob(gate_median, gate_mean, gate_scale, gate_weight, gate_bias, features, NULL);
    /* classes: [dog, non_dog]，sigmoid 输出 P(class[1]) = P(non_dog)。dog 概率 = 1 - p。 */
    float p_dog = 1.0f - p_non_dog;
    if (dog_prob) *dog_prob = p_dog;
    return p_dog > 0.5f ? 1 : 0;
}

/* 状态三分类：softmax argmax，返回类别索引 + 概率数组。 */
int dog_state_classify(const float *features, double probs_out[3]) {
    softmax_probs(state_median, state_mean, state_scale, state_weight, state_bias,
                  STATE_LOGIT_COUNT, features, probs_out);
    int best = 0;
    for (int c = 1; c < STATE_CLASS_COUNT; ++c) if (probs_out[c] > probs_out[best]) best = c;
    return best;
}
