#include "network.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstring>
#include <fstream>
#include <optional>
#include <stdexcept>
namespace gungi {
namespace {
std::vector<int> features_view(const Position &p, int view) {
  std::vector<int> f;
  f.reserve(84);
  for (int q = 0; q < 81; ++q) {
    const auto &tower = p.board[view ? 80 - q : q];
    for (int t = 0; t < tower.size; ++t) {
      const int v = view ? 1 + (tower.p[t] + 13) % 28 : tower.p[t];
      f.push_back((q * 3 + t) * 28 + v - 1);
    }
  }
  for (int c = 0; c < 2; ++c)
    for (int k = 0; k < 14; ++k)
      f.push_back(6804 + (c * 14 + k) * 5 + p.hand[c ^ view][k]);
  f.push_back(6944 + (p.turn ^ view));
  f.push_back(6946 + int(p.draft));
  f.push_back(6948 + (p.first ^ view));
  f.push_back(6950 + int(p.done[view]));
  f.push_back(6952 + int(p.done[1 ^ view]));
  return f;
}
} // namespace
std::vector<int> features(const Position &p, bool relative) {
  return features_view(p, relative ? p.turn : 0);
}
void Network::add_feature(Accumulator &cache, int index, int sign) {
  if (integer)
    for (int j = 0; j < hidden_size; ++j)
      cache.quantized[j] += sign * int(qw1[index * hidden_size + j]);
  else
    for (int j = 0; j < hidden_size; ++j)
      cache.floating[j] += sign * w1[index * hidden_size + j];
}
void Network::begin_search(const Position &p, bool enabled) {
  direct = enabled && ready && !linear;
  float_stack.clear();
  if (!direct)
    return;
  if (!integer)
    float_stack.reserve(80);
  for (int view = 0; view < (relative ? 2 : 1); ++view) {
    auto &cache = caches[view];
    if (integer)
      std::copy(qb1.begin(), qb1.end(), cache.quantized.begin());
    else
      std::copy(b1.begin(), b1.end(), cache.floating.begin());
    cache.previous.clear();
    for (int index : features_view(p, view))
      add_feature(cache, index, 1);
  }
}
void Network::end_search() {
  if (direct)
    for (auto &cache : caches)
      cache.previous.clear();
  direct = false;
  float_stack.clear();
}
void Network::update(const Position &p, const Move &m, const Undo &u,
                     bool undo) {
  if (!direct)
    return;
  if (!integer) {
    if (undo) {
      assert(!float_stack.empty());
      for (int view = 0; view < (relative ? 2 : 1); ++view)
        caches[view].floating = float_stack.back()[view];
      float_stack.pop_back();
      return;
    }
    // Restoring the parent prevents roundoff accumulating across sibling lines.
    float_stack.push_back({caches[0].floating, caches[1].floating});
  }
  const int sign = undo ? -1 : 1;
  for (int view = 0; view < (relative ? 2 : 1); ++view) {
    auto &cache = caches[view];
    auto change = [&](int before, int after) {
      if (before == after)
        return;
      if (before >= 0)
        add_feature(cache, before, -sign);
      if (after >= 0)
        add_feature(cache, after, sign);
    };
    auto tower = [&](int square, const Tower &before) {
      if (square < 0)
        return;
      const auto &after = p.board[square];
      const int q = view ? 80 - square : square;
      auto index = [&](int level, int v) {
        if (!v)
          return -1;
        if (view)
          v = 1 + (v + 13) % 28;
        return (q * 3 + level) * 28 + v - 1;
      };
      for (int t = 0; t < 3; ++t)
        change(index(t, t < before.size ? before.p[t] : 0),
               index(t, t < after.size ? after.p[t] : 0));
    };
    tower(m.from, u.from);
    tower(m.to, u.to);
    for (int k = 0; k < 14; ++k) {
      const int base = 6804 + ((u.turn ^ view) * 14 + k) * 5;
      change(base + u.hand[k], base + p.hand[u.turn][k]);
    }
    change(6944 + (u.turn ^ view), 6944 + (p.turn ^ view));
    change(6946 + int(u.draft), 6946 + int(p.draft));
    change(6950 + int(u.done[view]), 6950 + int(p.done[view]));
    change(6952 + int(u.done[1 ^ view]), 6952 + int(p.done[1 ^ view]));
  }
}
void Network::load(const std::string &path) {
  std::ifstream in(path, std::ios::binary);
  if (!in)
    throw std::invalid_argument("cannot open model");
  std::vector<char> bytes((std::istreambuf_iterator<char>(in)), {});
  if (bytes.size() < 32 || std::memcmp(bytes.data(), "KOKONN01", 8))
    throw std::invalid_argument("invalid model header");
  uint32_t dims[4];
  uint64_t expected;
  std::memcpy(dims, bytes.data() + 8, 16);
  std::memcpy(&expected, bytes.data() + 24, 8);
  const bool linear_format = dims[3] == 7 || dims[3] == 8;
  if (linear_format
          ? (dims[0] !=
                 uint32_t(dims[3] == 8 ? EXTENDED_FEATURES : LINEAR_FEATURES) ||
             dims[1] != 1 || dims[2] != 1)
          : (dims[0] != FEATURES || (dims[1] != 64 && dims[1] != HIDDEN) ||
             dims[2] != SECOND || dims[3] > 6))
    throw std::invalid_argument("incompatible model dimensions/format");
  uint64_t hash = 1469598103934665603ULL;
  for (size_t i = 32; i < bytes.size(); ++i) {
    hash ^= static_cast<unsigned char>(bytes[i]);
    hash *= 1099511628211ULL;
  }
  if (hash != expected)
    throw std::invalid_argument("model checksum mismatch");
  Network next;
  if (linear_format) {
    next.linear_size = int(dims[0]);
    if (bytes.size() != 32 + next.linear_size * sizeof(int32_t))
      throw std::invalid_argument("unexpected model payload");
    std::memcpy(next.linear_weights.data(), bytes.data() + 32,
                next.linear_size * sizeof(int32_t));
    for (int32_t value : next.linear_weights)
      if (value < -30000 || value > 30000)
        throw std::invalid_argument("invalid model value");
    next.ready = next.integer = next.linear = true;
    for (int i = LINEAR_FEATURES; i < next.linear_size; ++i)
      if (next.linear_weights[i])
        next.strategic_groups |= 1 << ((i - LINEAR_FEATURES) / 2);
    *this = std::move(next);
    return;
  }
  next.hidden_size = int(dims[1]);
  next.relative = dims[3] >= 3;
  next.residual = dims[3] >= 5;
  next.integer = dims[3] == 1 || dims[3] == 2 || dims[3] == 4 || dims[3] == 6;
  next.scale = dims[3] == 2 || dims[3] == 4 || dims[3] == 6 ? 512 : 256;
  size_t offset = 32;
  auto read = [&](auto &vector, size_t count) {
    using T = typename std::decay_t<decltype(vector)>::value_type;
    size_t n = count * sizeof(T);
    if (offset + n > bytes.size())
      throw std::invalid_argument("truncated model");
    vector.resize(count);
    std::memcpy(vector.data(), bytes.data() + offset, n);
    offset += n;
  };
  if (next.integer) {
    std::vector<int32_t> last;
    read(next.qw1, FEATURES * next.hidden_size);
    read(next.qb1, next.hidden_size);
    read(next.qw2, SECOND * next.hidden_size);
    read(next.qb2, SECOND);
    read(next.qw3, SECOND);
    read(last, 1);
    next.qb3 = last[0];
    auto bounded = [](const auto &values, int64_t limit) {
      for (auto value : values)
        if (int64_t(value) < -limit || int64_t(value) > limit)
          throw std::invalid_argument("invalid model value");
    };
    for (const auto *weights : {&next.qw1, &next.qw2, &next.qw3})
      bounded(*weights, 64 * next.scale);
    bounded(next.qb1, 64 * next.scale);
    bounded(next.qb2, int64_t(64) * next.scale * next.scale);
    bounded(last, int64_t(64) * next.scale * next.scale);
  } else {
    std::vector<float> last;
    read(next.w1, FEATURES * next.hidden_size);
    read(next.b1, next.hidden_size);
    read(next.w2, SECOND * next.hidden_size);
    read(next.b2, SECOND);
    read(next.w3, SECOND);
    read(last, 1);
    next.b3 = last[0];
    for (const auto *v :
         {&next.w1, &next.b1, &next.w2, &next.b2, &next.w3, &last})
      for (float x : *v)
        if (!std::isfinite(x) || std::abs(x) > 64)
          throw std::invalid_argument("invalid model value");
  }
  if (offset != bytes.size())
    throw std::invalid_argument("unexpected model payload");
  next.ready = true;
  *this = std::move(next);
}
float Network::predict(const Position &p, bool incremental) {
  if (!ready)
    throw std::logic_error("model not loaded");
  if (linear) {
    const auto basis = evaluation_features(p);
    int64_t score = 0;
    for (int i = 0; i < LINEAR_FEATURES; ++i)
      score += int64_t(basis[i]) * linear_weights[i];
    if (strategic_groups) {
      const auto extra = strategic_features(p, strategic_groups);
      for (int i = 0; i < STRATEGIC_FEATURES; ++i)
        score += int64_t(extra[i]) * linear_weights[LINEAR_FEATURES + i];
    }
    return float(std::clamp(score, int64_t(-20000), int64_t(20000)));
  }
  std::optional<Accumulator> rebuilt;
  if (direct && !incremental)
    rebuilt.emplace();
  auto &cache = rebuilt ? *rebuilt : caches[relative ? p.turn : 0];
  auto &previous = cache.previous;
  auto &accumulator = cache.floating;
  auto &qaccumulator = cache.quantized;
  if (!(direct && incremental)) {
    auto now = features(p, relative);
    if (!incremental || previous.empty()) {
      if (integer)
        std::copy(qb1.begin(), qb1.end(), qaccumulator.begin());
      else
        std::copy(b1.begin(), b1.end(), accumulator.begin());
      previous.clear();
    }
    auto update = [&](int index, int sign) { add_feature(cache, index, sign); };
    size_t a = 0, b = 0;
    while (a < previous.size() || b < now.size()) {
      if (a == previous.size()) {
        update(now[b++], 1);
        continue;
      }
      if (b == now.size()) {
        update(previous[a++], -1);
        continue;
      }
      if (previous[a] == now[b]) {
        ++a;
        ++b;
      } else if (previous[a] < now[b])
        update(previous[a++], -1);
      else
        update(now[b++], 1);
    }
    previous = std::move(now);
  }
  if (integer) {
    std::array<int, HIDDEN> activated{};
    for (int j = 0; j < hidden_size; ++j)
      activated[j] = std::clamp(qaccumulator[j], 0, scale);
    std::array<int, SECOND> hidden{};
    for (int i = 0; i < SECOND; ++i) {
      int64_t v = qb2[i];
      for (int j = 0; j < hidden_size; ++j)
        v += int64_t(qw2[i * hidden_size + j]) * activated[j];
      hidden[i] = std::clamp<int64_t>((v + scale / 2) / scale, 0, scale);
    }
    int64_t out = qb3;
    for (int i = 0; i < SECOND; ++i)
      out += int64_t(qw3[i]) * hidden[i];
    return float(out) * (600.0f / float(scale * scale));
  }
  std::array<float, HIDDEN> activated{};
  for (int j = 0; j < hidden_size; ++j)
    activated[j] = std::clamp(accumulator[j], 0.0f, 1.0f);
  float out = b3;
  for (int i = 0; i < SECOND; ++i) {
    float v = b2[i];
    for (int j = 0; j < hidden_size; ++j)
      v += w2[i * hidden_size + j] * activated[j];
    out += w3[i] * std::clamp(v, 0.0f, 1.0f);
  }
  return out * 600;
}
int Network::evaluate(const Position &p, bool incremental) {
  const int base = residual ? gungi::evaluate(p) : 0;
  return std::clamp(base + int(std::lround(predict(p, incremental))), -20000,
                    20000);
}
} // namespace gungi
