#ifndef PL_DOG_PREDICT_H
#define PL_DOG_PREDICT_H
#include <stdbool.h>
#include "dog_model_params.h"

/* 物种门控：0=cat, 1=dog */
int dog_species_classify(const float *features, float *dog_prob);
/* 狗门控：0=non_dog, 1=dog */
int dog_gate_classify(const float *features, float *dog_prob);
/* 状态三分类：返回类别索引（active/alert/rest），probs_out 填 3 个 softmax 概率 */
int dog_state_classify(const float *features, double probs_out[3]);

#endif
