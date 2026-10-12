// Minimal two-thread DSU correctness harness for tools supporting C++20 atomics.
// The checker version and memory model must be recorded separately.
#define SAW_DSU_NO_MAIN
#include "../src/dsu.cpp"
#include <cassert>
int main() {
    DSU d(4,"P1");
    std::thread a([&]{Counts c; d.unite(0,3,c);d.unite(1,2,c);});
    std::thread b([&]{Counts c; d.unite(0,2,c);d.unite(1,3,c);});
    a.join();b.join();
    assert(d.validate());
    Counts c;
    auto r=d.find(3,c);
    assert(r==d.find(0,c));
    assert(r==d.find(1,c));
    assert(r==d.find(2,c));
}
