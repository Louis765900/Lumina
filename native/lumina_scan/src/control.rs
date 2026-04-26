use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

#[derive(Clone, Debug)]
pub struct StopControl {
    flag: Arc<AtomicBool>,
}

impl StopControl {
    pub fn new() -> Self {
        Self {
            flag: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn from_flag(flag: Arc<AtomicBool>) -> Self {
        Self { flag }
    }

    pub fn flag(&self) -> Arc<AtomicBool> {
        self.flag.clone()
    }

    pub fn stop(&self) {
        self.flag.store(true, Ordering::SeqCst);
    }

    pub fn should_stop(&self) -> bool {
        self.flag.load(Ordering::SeqCst)
    }
}

impl Default for StopControl {
    fn default() -> Self {
        Self::new()
    }
}
