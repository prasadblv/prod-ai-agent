from agent.memory.memory import InMemoryStore


class TestInMemoryStoreGetContext:
    def test_unknown_session_returns_empty_list(self):
        store = InMemoryStore()
        assert store.get_context("nope") == []

    def test_returns_stored_turns_in_order(self):
        store = InMemoryStore()
        store.store("s1", "hi", "hello")
        store.store("s1", "how are you", "good")
        history = store.get_context("s1")
        assert history == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "how are you"},
            {"role": "assistant", "content": "good"},
        ]

    def test_sessions_are_isolated(self):
        store = InMemoryStore()
        store.store("s1", "hi", "hello")
        store.store("s2", "yo", "sup")
        assert store.get_context("s1") == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert store.get_context("s2") == [
            {"role": "user", "content": "yo"},
            {"role": "assistant", "content": "sup"},
        ]


class TestInMemoryStoreTrimming:
    def test_history_within_limit_is_not_trimmed(self):
        store = InMemoryStore(max_turns=2)
        store.store("s1", "a", "A")
        store.store("s1", "b", "B")
        assert len(store.get_context("s1")) == 4

    def test_history_beyond_limit_keeps_only_the_most_recent_turns(self):
        store = InMemoryStore(max_turns=2)
        store.store("s1", "a", "A")
        store.store("s1", "b", "B")
        store.store("s1", "c", "C")

        history = store.get_context("s1")

        assert len(history) == 4
        assert history == [
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "B"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "C"},
        ]
        assert all(isinstance(turn, dict) for turn in history)
