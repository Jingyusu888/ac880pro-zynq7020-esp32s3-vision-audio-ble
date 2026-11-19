/* Frozen Python extractor port. Double intermediates preserve low-power FFT bins.
 * No training, gain, denoising, or different resampling algorithm is performed. */
#include <stdint.h>
#include "audio_frontend.h"
#include "frontend_tables_precise.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#define N 1024
#define MAX_FRAMES 126
#define BINS 513
#define EPS 1e-12
#define PI 3.14159265358979323846264338327950288
typedef struct { size_t count; double mean, m2; } stats_t;
struct pl_frontend {
    double re[N], im[N], tw_re[N/2], tw_im[N/2];
    double power[BINS], scratch[BINS], frame[N];
    double mel[64][MAX_FRAMES], mfcc[20][MAX_FRAMES];
};
static void add(stats_t *s, double x) {
    if (!isfinite(x)) return;
    double d = x - s->mean;
    s->count++; s->mean += d / (double)s->count;
    s->m2 += d * (x - s->mean);
}
static double mean(const stats_t *s) { return s->count ? s->mean : NAN; }
static double stddev(const stats_t *s) {
    return s->count ? sqrt(fmax(0.0, s->m2 / (double)s->count)) : NAN;
}
static int compare_double(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static double percentile(const double *sorted, size_t n, double p) {
    double at = (n - 1) * p;
    size_t lo = (size_t)at, hi = lo + 1 < n ? lo + 1 : lo;
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
}
size_t pl_frontend_workspace_size(void) { return sizeof(pl_frontend_t); }
pl_frontend_t *pl_frontend_init(void *memory, size_t bytes) {
    if (!memory || bytes < sizeof(pl_frontend_t)) return NULL;
    pl_frontend_t *w = memory;
    memset(w, 0, sizeof(*w));
    for (int k = 0; k < N/2; k++) {
        w->tw_re[k] = cos(-2.0*PI*k/N);
        w->tw_im[k] = sin(-2.0*PI*k/N);
    }
    return w;
}
int32_t pl_i2s_sample24(uint32_t word, int high_aligned) {
    uint32_t value = high_aligned ? word >> 8 : word & 0xffffffu;
    /* Avoid implementation-defined signed shifts or conversions. */
    return (int32_t)(value & 0x7fffffu) - (int32_t)(value & 0x800000u);
}
static void fft(pl_frontend_t *w) {
    for (unsigned i=1,j=0; i<N; i++) {
        unsigned bit=N>>1;
        for (; j & bit; bit>>=1) j ^= bit;
        j ^= bit;
        if (i<j) {
            double tmp=w->re[i]; w->re[i]=w->re[j]; w->re[j]=tmp;
        }
    }
    memset(w->im, 0, sizeof(w->im));
    for (unsigned len=2; len<=N; len<<=1) {
        unsigned half=len/2, stride=N/len;
        for (unsigned base=0; base<N; base+=len) for(unsigned j=0;j<half;j++) {
            unsigned a=base+j,b=a+half,t=j*stride;
            double tr=w->re[b]*w->tw_re[t]-w->im[b]*w->tw_im[t];
            double ti=w->re[b]*w->tw_im[t]+w->im[b]*w->tw_re[t];
            w->re[b]=w->re[a]-tr; w->im[b]=w->im[a]-ti;
            w->re[a]+=tr; w->im[a]+=ti;
        }
    }
}
static double sample(const float *pcm, size_t count, int index) {
    return index>=0 && index<(int)count ? pcm[index] : 0.0;
}
int pl_extract(pl_frontend_t *w, const float *pcm, size_t count,
               float out[PL_FEATURES], pl_yield_fn yield, void *context) {
    int frames = count==PL_PCM_SAMPLES ? 126 : (count==PL_PCM_SAMPLES_2S ? 64 : -1);
    int f0_frames = count==PL_PCM_SAMPLES ? 33 : (count==PL_PCM_SAMPLES_2S ? 17 : -1);
    if (!w || !pcm || !out || frames<0 || f0_frames<0) return -1;
    double peak=0;
    for (size_t i=0;i<count;i++) {
        if(!isfinite(pcm[i])) return -2;
        peak=fmax(peak,fabs(pcm[i]));
    }
    stats_t rms={0}, rms_db={0}, zcr={0}, centroid={0}, bw={0},
            roll85={0}, roll95={0}, flatness={0}, contrast={0};
    double max_rms=0, total_power=0, bands[4]={0}, global_max=-INFINITY;
    unsigned silent=0;
    const int edges[6]={0,32,64,128,256,513};
    for(int frame=0;frame<frames;frame++) {
        double sq=0; unsigned crossings=0;
        for(int i=0;i<N;i++) {
            double x=sample(pcm,count,frame*256+i-512);
            w->frame[i]=x; sq+=x*x;
            if(i && signbit(x)!=signbit(w->frame[i-1])) crossings++;
            w->re[i]=x*pl_hann64[i];
        }
        double r=sqrt(sq/N), db=20*log10(fmax(r,EPS));
        add(&rms,r); add(&rms_db,db); max_rms=fmax(max_rms,r);
        add(&zcr,(double)crossings/(N-1)); silent += db < -50.0;
        fft(w);
        double mag_sum=EPS, mag_freq=0, p_sum=0, log_sum=0;
        for(int k=0;k<BINS;k++) {
            double p=w->re[k]*w->re[k]+w->im[k]*w->im[k];
            double m=sqrt(p), f=k*(8000.0/N);
            w->power[k]=p; mag_sum+=m; mag_freq+=m*f;
            p_sum+=p; log_sum+=log(fmax(p,EPS));
            bands[k<64 ? 0 : k<128 ? 1 : k<256 ? 2 : 3]+=p;
        }
        double c=mag_freq/mag_sum, width=0, cumulative=0;
        int r85=-1,r95=-1;
        for(int k=0;k<BINS;k++) {
            double d=k*(8000.0/N)-c;
            width+=sqrt(w->power[k])*d*d;
            cumulative+=w->power[k];
            if(r85<0 && cumulative>=p_sum*.85) r85=k;
            if(r95<0 && cumulative>=p_sum*.95) r95=k;
        }
        add(&centroid,c); add(&bw,sqrt(width/mag_sum));
        add(&roll85,(r85<0 ? 0:r85)*(8000.0/N));
        add(&roll95,(r95<0 ? 0:r95)*(8000.0/N));
        add(&flatness,exp(log_sum/BINS)/fmax(p_sum/BINS,EPS));
        total_power+=p_sum;
        for(int band=0;band<5;band++) {
            int n=edges[band+1]-edges[band];
            for(int j=0;j<n;j++) w->scratch[j]=10*log10(fmax(w->power[edges[band]+j],EPS));
            qsort(w->scratch,(size_t)n,sizeof(double),compare_double);
            add(&contrast,percentile(w->scratch,n,.9)-percentile(w->scratch,n,.1));
        }
        int offset=0;
        for(int mel=0;mel<64;mel++) {
            double p=0;
            for(int j=0;j<pl_mel_count64[mel];j++)
                p+=pl_mel_weights64[offset++]*w->power[pl_mel_first64[mel]+j];
            double value=10*log10(fmax(p,EPS));
            w->mel[mel][frame]=value; global_max=fmax(global_max,value);
        }
        if(yield) yield(context);
    }
    int at=0;
#define PUT(v) out[at++]=(float)(v)
    PUT(mean(&rms)); PUT(stddev(&rms)); PUT(max_rms); PUT(mean(&rms_db));
    PUT(peak); PUT(peak/fmax(mean(&rms),EPS)); PUT(mean(&zcr)); PUT(stddev(&zcr));
    PUT((double)silent/frames); PUT(mean(&centroid)); PUT(stddev(&centroid));
    PUT(mean(&bw)); PUT(stddev(&bw)); PUT(mean(&roll85)); PUT(mean(&roll95));
    PUT(mean(&flatness)); PUT(stddev(&flatness)); PUT(mean(&contrast)); PUT(stddev(&contrast));
    for(int i=0;i<4;i++) PUT(bands[i]/fmax(total_power,EPS));
    for(int k=0;k<20;k++) for(int f=0;f<frames;f++) {
        double sum=0;
        for(int mel=0;mel<64;mel++) sum+=pl_dct64[k*64+mel]*(w->mel[mel][f]-global_max);
        w->mfcc[k][f]=sum;
    }
    for(int kind=0;kind<2;kind++) for(int stat=0;stat<2;stat++) for(int k=0;k<20;k++) {
        stats_t s={0};
        for(int f=0;f<frames;f++) {
            double value=w->mfcc[k][f];
            if(kind) value=f==0 ? w->mfcc[k][1]-w->mfcc[k][0] :
                f==frames-1 ? w->mfcc[k][f]-w->mfcc[k][f-1] :
                .5*(w->mfcc[k][f+1]-w->mfcc[k][f-1]);
            add(&s,value);
        }
        PUT(stat ? stddev(&s) : mean(&s));
    }
    for(int stat=0;stat<2;stat++) for(int mel=0;mel<64;mel++) {
        stats_t s={0};
        for(int f=0;f<frames;f++) add(&s,w->mel[mel][f]-global_max);
        PUT(stat ? stddev(&s):mean(&s));
    }
    stats_t f0={0}; int voiced=0;
    for(int f=0;f<f0_frames;f++) {
        double avg=0, corr0=0;
        for(int i=0;i<N;i++) { w->frame[i]=sample(pcm,count,f*N+i-512); avg+=w->frame[i]; }
        avg/=N;
        for(int i=0;i<N;i++) {
            w->frame[i]=(w->frame[i]-avg)*pl_hann64[i]; corr0+=w->frame[i]*w->frame[i];
        }
        if(20*log10(fmax(sqrt(corr0/N),EPS)) > -50 && corr0>EPS) {
            double best=-INFINITY; int lag=4;
            for(int k=4;k<=100;k++) {
                double corr=0;
                for(int i=0;i<N-k;i++) corr+=w->frame[i]*w->frame[i+k];
                if(corr>best) { best=corr; lag=k; }
            }
            if(best/corr0>=.2) { double value=8000.0/lag; w->scratch[voiced++]=value; add(&f0,value); }
        }
        if(yield) yield(context);
    }
    if(voiced) {
        qsort(w->scratch,(size_t)voiced,sizeof(double),compare_double);
        PUT(mean(&f0)); PUT(percentile(w->scratch,voiced,.5)); PUT(stddev(&f0));
        PUT(w->scratch[0]); PUT(w->scratch[voiced-1]); PUT(w->scratch[voiced-1]-w->scratch[0]);
    } else { for(int i=0;i<6;i++) PUT(NAN); }
    PUT((double)voiced/f0_frames);
#undef PUT
    return at==PL_FEATURES ? 0 : -3;
}
