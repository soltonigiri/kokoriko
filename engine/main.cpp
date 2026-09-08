#include "gungi.hpp"
#include "network.hpp"
#include "search.hpp"
#include <iostream>
#include <mutex>
#include <thread>
using namespace gungi;
int main(int argc, char **argv) {
  Network network;
  bool tuned = true, selective = false, model_after_draft = false;
  try {
    for (int i = 1; i < argc; ++i) {
      std::string flag = argv[i];
      if ((flag == "--model" || flag == "--model-after-draft") &&
          i + 1 < argc) {
        network.load(argv[++i]);
        model_after_draft = flag == "--model-after-draft";
      } else if (flag == "--tuned-search") {
        tuned = true;
        selective = false;
      } else if (flag == "--basic-search") {
        tuned = selective = false;
      } else if (flag == "--selective-search") {
        tuned = selective = true;
      } else
        throw std::invalid_argument(
            "usage: kokoriko [--model FILE | --model-after-draft FILE] "
            "[--tuned-search | --basic-search | "
            "--selective-search]");
    }
  } catch (const std::exception &e) {
    std::cerr << e.what() << std::endl;
    return 2;
  }
  Position p = Position::initial();
  std::vector<std::pair<Move, Undo>> stack;
  std::string line;
  std::atomic<bool> cancel{false}, busy{false};
  std::thread worker;
  std::mutex output;
  auto send = [&](const json &reply) {
    std::lock_guard lock(output);
    std::cout << reply.dump() << std::endl;
  };
  while (std::getline(std::cin, line)) {
    try {
      auto req = json::parse(line);
      std::string cmd = req.at("cmd");
      json result;
      if (cmd == "stop") {
        cancel = true;
        continue;
      } // notification: the pending search produces its one response
      if (cmd == "quit")
        break;
      if (busy.load())
        throw std::invalid_argument("search in progress; send stop first");
      if (worker.joinable())
        worker.join();
      if (cmd == "search") {
        SearchOptions options;
        options.tuned = req.value("tuned", tuned);
        options.selective =
            req.value("selective", req.contains("tuned") ? false : selective);
        if (options.selective)
          options.tuned = true;
        options.milliseconds = req.value("ms", 1000);
        options.max_depth = req.value("depth", 32);
        options.hash_mb = req.value("hash_mb", 32);
        options.qdepth = req.value("qdepth", 3);
        options.node_limit = req.value("nodes", uint64_t(0));
        if (options.milliseconds < 1 || options.milliseconds > 3600000 ||
            options.qdepth < 0 || options.qdepth > 8)
          throw std::invalid_argument("invalid search limits");
        cancel = false;
        busy = true;
        worker = std::thread([&, snapshot = p, options]() {
          try {
            Searcher search;
            // Keep the entire deployment search on its original evaluator,
            // even when a variation reaches the battle phase.
            const bool use_model =
                network.loaded() && (!model_after_draft || !snapshot.draft);
            auto r = search.run(
                snapshot, options, &cancel, [&](const Position &state) {
                  return use_model ? network.evaluate(state) : evaluate(state);
                });
            busy = false;
            send({{"ok", true}, {"result", encode(r)}});
          } catch (const std::exception &e) {
            busy = false;
            send({{"ok", false}, {"error", e.what()}});
          }
        });
        continue;
      }
      if (cmd == "new") {
        p = Position::initial(req.value("first", 0));
        stack.clear();
        result = encode(p);
      } else if (cmd == "position") {
        auto next = decode(req.at("position"));
        p = std::move(next);
        stack.clear();
        result = encode(p);
      } else if (cmd == "features")
        result = network.linear_model()
                     ? json(evaluation_features(p))
                     : json(features(p, network.relative_features()));
      else if (cmd == "linear_basis")
        result = {{"features", evaluation_features(p)},
                  {"weights", evaluation_weights()}};
      else if (cmd == "network") {
        if (!network.loaded())
          throw std::invalid_argument("no model loaded");
        float incremental = network.predict(p, true);
        float full = network.predict(p, false);
        result = {{"full", full}, {"incremental", incremental}};
      } else if (cmd == "state")
        result = encode(p);
      else if (cmd == "legal") {
        result = json::array();
        for (const auto &m : legal_moves(p))
          result.push_back(encode(m));
      } else if (cmd == "play") {
        auto m = decode_move(req.at("move"));
        auto moves = legal_moves(p);
        if (std::find(moves.begin(), moves.end(), m) == moves.end())
          throw std::invalid_argument("illegal move");
        auto u = make_move(p, m);
        stack.emplace_back(m, u);
        result = encode(p);
      } else if (cmd == "undo") {
        if (stack.empty())
          throw std::invalid_argument("no move to undo");
        auto [m, u] = stack.back();
        stack.pop_back();
        undo_move(p, m, u);
        result = encode(p);
      } else if (cmd == "status")
        result = {{"outcome", outcome(p)},
                  {"check", in_check(p, p.turn)},
                  {"eval", network.loaded() && (!model_after_draft || !p.draft)
                               ? network.evaluate(p)
                               : evaluate(p)}};
      else if (cmd == "perft") {
        int d = req.value("depth", 1);
        if (d < 0 || d > 5)
          throw std::invalid_argument("perft depth 0..5 required");
        result = perft(p, d);
      } else
        throw std::invalid_argument("unknown command");
      send({{"ok", true}, {"result", result}});
    } catch (const std::exception &e) {
      send({{"ok", false}, {"error", e.what()}});
    }
  }
  cancel = true;
  if (worker.joinable())
    worker.join();
}
