import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Container, Table, Spinner, Alert, Button, ProgressBar, Collapse, Card } from 'react-bootstrap';
import Layout from '../components/Layout';
import './SeriesDetail.css';

export default function SeriesDetail() {
  const { seriesTitle } = useParams();
  const [episodesBySeason, setEpisodesBySeason] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [jobs, setJobs] = useState({});
  const [libraryScan, setLibraryScan] = useState({ running: false, jobs: [] });
  const [expandedLogs, setExpandedLogs] = useState({}); // track which jobs' logs are expanded

  // Fetch episodes
  const loadEpisodes = () => {
    setLoading(true);
    setError(null);
    fetch(`/api/series/${encodeURIComponent(seriesTitle)}/episodes`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => {
        const grouped = data.reduce((acc, ep) => {
          const s = ep.season;
          (acc[s] = acc[s] || []).push(ep);
          return acc;
        }, {});
        setEpisodesBySeason(grouped);
      })
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  };

  // Poll library scan status
  useEffect(() => {
    const interval = setInterval(() => {
      fetch('/api/library-scan-status')
        .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
        .then(data => setLibraryScan(data))
        .catch(console.error);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // Poll all jobs for per-episode progress
  useEffect(() => {
    const interval = setInterval(() => {
      Object.values(jobs).forEach(job => {
        fetch(`/api/job-status/${job.id}`)
          .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
          .then(updated => setJobs(prev => ({ ...prev, [job.id]: updated })))
          .catch(console.error);
      });
    }, 3000);
    return () => clearInterval(interval);
  }, [jobs]);

  useEffect(() => { loadEpisodes(); }, [seriesTitle]);

  const startJob = (epKey, type) => {
    const url = type === 'replace' ? '/api/episodes/replace-async' : `/api/episode/${encodeURIComponent(epKey)}/tags`;
    const body = type === 'replace' ? { key: epKey } : { tag: 'override' };

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => {
        if (data.job_id) {
          setJobs(prev => ({ ...prev, [data.job_id]: { id: data.job_id, episode_key: epKey, status: 'queued', progress: 0, message: '', log: [] } }));
        }
      })
      .catch(console.error);
  };

  const toggleLog = (jobId) => {
    setExpandedLogs(prev => ({ ...prev, [jobId]: !prev[jobId] }));
  };

  const renderEpisodeActions = (ep) => {
    const job = Object.values(jobs).find(j => j.episode_key === ep.key);
    return !ep.matches ? (
      <>
        <Button
          variant="warning"
          size="sm"
          disabled={job && job.status === 'running'}
          onClick={() => startJob(ep.key, 'replace')}
          className="me-2"
        >
          {job ? `${job.status === 'running' ? 'Replacing…' : 'Queued…'}` : 'Replace'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={job && job.status === 'running'}
          onClick={() => startJob(ep.key, 'override')}
        >
          {job ? `${job.status === 'running' ? 'Overriding…' : 'Queued…'}` : 'Override'}
        </Button>
        {job && (
          <>
            <ProgressBar
              now={job.progress || 0}
              label={`${job.progress || 0}%`}
              className="mt-1"
              striped
              animated={job.status === 'running'}
              variant={job.status === 'error' ? 'danger' : 'info'}
            />
            <Button
              variant="link"
              size="sm"
              className="p-0 mt-1"
              onClick={() => toggleLog(job.id)}
            >
              {expandedLogs[job.id] ? 'Hide Logs' : 'View Logs'}
            </Button>
            <Collapse in={expandedLogs[job.id]}>
              <Card className="mt-1 mb-2" bg="dark" text="light">
                <Card.Body style={{ maxHeight: '200px', overflowY: 'auto', fontSize: '0.85rem' }}>
                  {job.log.map((line, idx) => <div key={idx}>{line}</div>)}
                </Card.Body>
              </Card>
            </Collapse>
          </>
        )}
      </>
    ) : null;
  };

  if (loading) return (
    <Layout><Container className="py-4 text-center"><Spinner animation="border" /></Container></Layout>
  );

  if (error) return (
    <Layout>
      <Container className="py-4">
        <Alert variant="danger">Error: {error.toString()}</Alert>
        <Button as={Link} to="/" variant="outline-light" className="mt-2">← Back</Button>
      </Container>
    </Layout>
  );

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button as={Link} to="/" variant="outline-light" className="mb-3">← Back</Button>

        {/* Global library scan status */}
        {libraryScan.running && (
          <Alert variant="info">
            <Spinner animation="border" size="sm" className="me-2" />
            Analyzer / library scan is currently running…
            {libraryScan.jobs.map(job => (
              <Collapse in={true} key={job.id}>
                <Card className="mt-2 mb-2" bg="dark" text="light">
                  <Card.Body style={{ maxHeight: '150px', overflowY: 'auto', fontSize: '0.85rem' }}>
                    {job.log.map((line, idx) => <div key={idx}>{line}</div>)}
                  </Card.Body>
                </Card>
              </Collapse>
            ))}
          </Alert>
        )}

        <div className="table-wrapper">
          {Object.keys(episodesBySeason)
            .sort((a, b) => a - b)
            .map(seasonNum => (
              <section key={seasonNum} className="season-block mb-5">
                <h2 className="page-subtitle mb-3">Season {seasonNum}</h2>
                <Table striped hover responsive variant="dark">
                  <thead>
                    <tr>
                      <th>Match?</th>
                      <th>Code</th>
                      <th>Expected Title</th>
                      <th>Actual Title</th>
                      <th>Confidence</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {episodesBySeason[seasonNum].map(ep => (
                      <tr key={ep.key}>
                        <td>{ep.matches ? '✅' : '❌'}</td>
                        <td>{ep.code}</td>
                        <td>
                          <Button
                            variant="link"
                            as={Link}
                            to={`/episode/${encodeURIComponent(ep.key)}`}
                            className="p-0 expected-link text-light"
                          >
                            {ep.expectedTitle}
                          </Button>
                        </td>
                        <td>{ep.actualTitle}</td>
                        <td>{ep.confidence}</td>
                        <td>{renderEpisodeActions(ep)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </section>
            ))}
        </div>
      </Container>
    </Layout>
  );
}
