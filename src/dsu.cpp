#include <atomic>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include <stdexcept>
#include <sstream>

using Clock = std::chrono::steady_clock;
using U64 = uint64_t;
struct Counts { U64 loads=0, cas=0, retries=0, depth=0; };
static U64 pack(uint32_t parent,uint32_t version){return (U64(version)<<32)|parent;}
static uint32_t parent(U64 word){return uint32_t(word);}
static uint32_t version(U64 word){return uint32_t(word>>32);}

class DSU {
  std::vector<std::atomic<U64>> node;
  std::mutex coarse;
  std::string method;
  bool strict;
  bool compress;
  std::memory_order load_order()const{return strict?std::memory_order_seq_cst:method=="A2"?std::memory_order_relaxed:std::memory_order_acquire;}
  std::memory_order success_order()const{return strict?std::memory_order_seq_cst:method=="A2"?std::memory_order_relaxed:std::memory_order_acq_rel;}
  std::memory_order failure_order()const{return strict?std::memory_order_seq_cst:method=="A2"?std::memory_order_relaxed:std::memory_order_acquire;}
public:
  DSU(uint32_t n,std::string m):node(n),method(std::move(m)),strict(method=="B4"),compress(method=="A3") {
    for(uint32_t i=0;i<n;i++)node[i].store(pack(i,0),std::memory_order_relaxed);
  }
  uint32_t root(uint32_t x, Counts &c) {
    for(;;) {
      ++c.loads;U64 w=node[x].load(load_order());
      uint32_t p=parent(w);
      if(p==x)return x;
      if(p>=node.size() || p>=x)throw std::runtime_error("parent monotonicity violation");
      if(compress){
        ++c.loads;U64 pw=node[p].load(load_order());
        uint32_t gp=parent(pw);
        if(gp!=p && gp<p){
          U64 expected=w;
          ++c.cas;
          if(!node[x].compare_exchange_strong(expected,pack(gp,version(w)+1),success_order(),failure_order()))++c.retries;
        }
      }
      ++c.depth;x=p;
    }
  }
  bool unite(uint32_t x,uint32_t y,Counts&c,int pause_us=0) {
    if(method=="B1" || method=="B2"){
      std::lock_guard<std::mutex> guard(coarse);
      return unite_inner(x,y,c,pause_us);
    }
    return unite_inner(x,y,c,pause_us);
  }
  uint32_t find(uint32_t x,Counts&c){
    if(method=="B1" || method=="B2"){
      std::lock_guard<std::mutex>guard(coarse);return root(x,c);
    }
    return root(x,c);
  }
  bool unite_inner(uint32_t x,uint32_t y,Counts&c,int pause_us){
    for(;;){
      uint32_t rx=root(x,c),ry=root(y,c);
      if(rx==ry)return false;
      uint32_t high=std::max(rx,ry),low=std::min(rx,ry);
      ++c.loads;U64 expected=node[high].load(load_order());
      if(parent(expected)!=high){++c.retries;continue;}
      if(pause_us>0)std::this_thread::sleep_for(std::chrono::microseconds(pause_us));
      U64 desired=pack(low,(method=="A1" || method=="B3")?0:version(expected)+1);
      ++c.cas;
      if(node[high].compare_exchange_strong(expected,desired,success_order(),failure_order()))return true;
      ++c.retries;
    }
  }
  bool validate() {
    for(uint32_t i=0;i<node.size();++i){
      uint32_t p=parent(node[i].load(std::memory_order_seq_cst));
      if(p>=node.size()||p>i||(p==i && false))return false;
    }
    return true;
  }
  std::vector<uint32_t> snapshot(){
    std::vector<uint32_t>v;v.reserve(node.size());
    for(auto &a:node)v.push_back(parent(a.load()));
    return v;
  }
};
struct Operation {uint32_t x=0,y=0;bool is_find=false;int pause=0;};
struct Record{int tid;size_t idx;Operation o;U64 start,end;int result;Counts counts;};
static U64 nanosec(){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();}
static std::string getarg(int argc,char**argv,std::string key,std::string def){for(int i=1;i<argc-1;i++)if(argv[i]==key)return argv[i+1];return def;}
static int bounded(std::string s,int low,int high){long v=std::stol(s);if(v<low||v>high)throw std::runtime_error("argument out of bounds");return int(v);}
static std::vector<Operation> generate(int n,int ops,int tid,int seed,std::string work,double find_rate,double pause_rate,int pause_us){
  std::mt19937 rng(uint32_t(seed+7919*tid));
  std::uniform_int_distribution<int> node(0,n-1), dice(0,999999);
  std::vector<Operation> out;out.reserve(ops);
  for(int i=0;i<ops;i++){
    Operation o;int a=node(rng),b=node(rng);
    if(work=="W2" || work=="W5") {a=0;b=node(rng)%std::min(n,8);}
    else if(work=="W3") {a=(i+tid)%n;b=std::min(n-1,a+1);}
    else if(work=="W4") {a=node(rng)%(std::max(1,n/2));b=std::max(0,n/2)+node(rng)%std::max(1,n-n/2);}
    else if(work=="W7") {a=node(rng);b=node(rng);}
    else if(work=="W8") {a=node(rng);b=node(rng);}
    o.x=uint32_t(a);o.y=uint32_t(std::min(n-1,b));
    double rate=work=="W7"?0.95:work=="W8"?0.10:find_rate;
    o.is_find=dice(rng)<int(rate*1000000);
    if(work=="W3" && i < n/2)o.is_find=false;
    o.pause=dice(rng)<int(pause_rate*1000000)?pause_us:0;
    out.push_back(o);
  }return out;
}
static void print_record(const Record&r){
  std::cout<<"{\"kind\":\"operation\",\"thread\":"<<r.tid<<",\"index\":"<<r.idx<<",\"op\":\""<<(r.o.is_find?"find":"unite")<<"\",\"x\":"<<r.o.x<<",\"y\":"<<r.o.y<<",\"start_ns\":"<<r.start<<",\"end_ns\":"<<r.end<<",\"result\":"<<r.result<<"}\n";
}
#ifndef SAW_DSU_NO_MAIN
int main(int argc,char**argv){try {
  std::string method=getarg(argc,argv,"--method","P1"),work=getarg(argc,argv,"--workload","W1");
  int n=bounded(getarg(argc,argv,"--n","64"),2,1000000);
  int nt=bounded(getarg(argc,argv,"--threads","2"),1,32);
  int ops=bounded(getarg(argc,argv,"--ops","150"),1,10000000);
  int seed=std::stoi(getarg(argc,argv,"--seed","42"));
  int pause_us=bounded(getarg(argc,argv,"--pause-us","0"),0,1000000);
  double pause_rate=std::stod(getarg(argc,argv,"--pause-rate","0"));
  double find_rate=std::stod(getarg(argc,argv,"--find-rate","0.5"));
  bool history=getarg(argc,argv,"--history","0")=="1";
  if(pause_rate<0||pause_rate>1||find_rate<0||find_rate>1)throw std::runtime_error("rate must be within [0,1]");
  if(method!="B1"&&method!="B2"&&method!="B3"&&method!="B4"&&method!="P1"&&method!="A1"&&method!="A2"&&method!="A3")throw std::runtime_error("invalid method");
  DSU dsu(uint32_t(n),method);
  if(work=="W7") for(int i=n-1;i>0;--i){Counts init;dsu.unite(uint32_t(i),uint32_t(i-1),init);}
  std::vector<std::vector<Operation>> workloads;
  for(int t=0;t<nt;t++)workloads.push_back(generate(n,ops,t,seed,work,find_rate,pause_rate,pause_us));
  std::vector<std::vector<Record>> histories(nt);
  std::vector<Counts> counters(nt);
  std::vector<std::vector<U64>> timings(nt);
  std::vector<std::thread> workers;
  std::atomic<int> ready{0};std::atomic<bool> go{false};
  for(int tid=0;tid<nt;tid++){
    workers.emplace_back([&,tid](){
      ready.fetch_add(1);while(!go.load())std::this_thread::yield();
      for(size_t j=0;j<workloads[tid].size();++j){
        auto o=workloads[tid][j];Counts local;U64 begin=nanosec();
        int result=o.is_find?int(dsu.find(o.x,local)):int(dsu.unite(o.x,o.y,local,o.pause));
        U64 end=nanosec();
        counters[tid].loads+=local.loads;counters[tid].cas+=local.cas;
        counters[tid].retries+=local.retries;counters[tid].depth+=local.depth;
        if(j%std::max(size_t(1),workloads[tid].size()/10000)==0)timings[tid].push_back(end-begin);
        if(history)histories[tid].push_back({tid,j,o,begin,end,result,local});
      }
    });
  }
  while(ready.load()!=nt)std::this_thread::yield();
  U64 started=nanosec();go.store(true);
  for(auto &thread:workers)thread.join();
  U64 elapsed=nanosec()-started;
  Counts total;for(auto c:counters){total.loads+=c.loads;total.cas+=c.cas;total.retries+=c.retries;total.depth+=c.depth;}
  std::vector<U64> latency;for(auto &v:timings[0])latency.push_back(v);
  for(int t=1;t<nt;++t)for(auto v:timings[t])latency.push_back(v);
  std::sort(latency.begin(),latency.end());
  auto quantile=[&](double q)->U64{return latency.empty()?0:latency[std::min(latency.size()-1,size_t(q*(latency.size()-1)))];};
  bool valid=dsu.validate();
  if(history)for(const auto &h:histories)for(const auto&r:h)print_record(r);
  std::cout<<"{\"kind\":\"summary\",\"method\":\""<<method<<"\",\"workload\":\""<<work<<"\",\"n\":"<<n<<",\"threads\":"<<nt<<",\"operations\":"<<U64(nt)*ops<<",\"elapsed_ns\":"<<elapsed<<",\"throughput\":"<<(U64(nt)*ops*1e9/std::max(U64(1),elapsed))<<",\"p50_ns\":"<<quantile(0.50)<<",\"p95_ns\":"<<quantile(0.95)<<",\"p99_ns\":"<<quantile(0.99)<<",\"loads\":"<<total.loads<<",\"cas\":"<<total.cas<<",\"retries\":"<<total.retries<<",\"depth\":"<<total.depth<<",\"valid\":"<<(valid?"true":"false")<<",\"parents\":[";
  if(history || n<=1000){auto v=dsu.snapshot();for(size_t i=0;i<v.size();i++){if(i)std::cout<<",";std::cout<<v[i];}}
  std::cout<<"]}\n";return valid?0:2;
} catch(const std::exception&e){std::cerr<<"ERROR: "<<e.what()<<"\n";return 1;}}

#endif // SAW_DSU_NO_MAIN
