import React, { useEffect, useState } from 'react';
import {
  Container,
  Row,
  Col,
  Card,
  Spinner,
  Alert,
  ProgressBar,
  Table
} from 'react-bootstrap';
import Layout from '../components/Layout';

export default function Overview() {
  const [stats, setStats]           = useState(null);
  const [mismatches, setMismatches] = useState([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch('/api/stats').then(res => res.ok ? res.json() : Promise.reject(res.statusText)),
      fetch('/api/mismatches').then(res => res.ok ? res.json() : Promise.reject(res.statusText))
    ])
      .then(([statsData, mismatchData]) => {
        setStats(statsData);
        setMismatches(mismatchData);
      })
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Layout><Container className="py-4 text-center"><Spinner animation="border" /></Container></Layout>
    );
  }
  if (error) {
    return (
      <Layout><Container className="py-4"><Alert variant="danger">Error: {error}</Alert></Container></Layout>
    );
  }

  const {
    totalEpisodes,
    totalShows,
    totalOverrides,
    totalMissingTitles,
    totalMatches,
    totalMismatches,
    avgConfidence
  } = stats;

  // percentages for the health bar
  const pctMatches   = Math.round((totalMatches / totalEpisodes) * 100);
  const pctOverrides = Math.round((totalOverrides / totalEpisodes) * 100);
  const pctMismatches= Math.round((totalMismatches / totalEpisodes) * 100);
  const pctMissing   = Math.round((totalMissingTitles / totalEpisodes) * 100);

  return (
    <Layout>
      <Container fluid className="py-4">
        <h1 className="mb-4">Library Overview</h1>

        {/* Summary Cards */}
        <Row className="g-4 mb-5">
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Total Shows</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalShows}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Total Episodes</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalEpisodes}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Matched Episodes</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalMatches}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Overrides</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalOverrides}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Problematic</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalMismatches}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Missing Titles</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{totalMissingTitles}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col xs={6} md={3}>
            <Card bg="dark" text="light" className="text-center">
              <Card.Body>
                <Card.Title>Avg. Confidence</Card.Title>
                <Card.Text style={{ fontSize:'2rem' }}>{avgConfidence}</Card.Text>
              </Card.Body>
            </Card>
          </Col>
        </Row>

        {/* Episode Health Bar */}
        <h2 className="mb-3">Episode Health</h2>
        <Card bg="dark" text="light" className="mb-5">
          <Card.Body>
            <ProgressBar>
              <ProgressBar now={pctMatches}   label={`Matched ${pctMatches}%`}   variant="success" key={1}/>
              <ProgressBar now={pctOverrides} label={`Overrides ${pctOverrides}%`} variant="info"    key={2}/>
              <ProgressBar now={pctMismatches}label={`Problematic ${pctMismatches}%`}variant="danger" key={3}/>
              <ProgressBar now={pctMissing}   label={`Missing ${pctMissing}%`}   variant="warning" key={4}/>
            </ProgressBar>
          </Card.Body>
        </Card>

        {/* Problematic Episodes by Series */}
        <h2 className="mb-3">Problematic Episodes by Series</h2>
        <Table striped bordered hover responsive variant="dark">
          <thead>
            <tr><th>Series</th><th>Count</th></tr>
          </thead>
          <tbody>
            {mismatches.map(({ seriesTitle, count }) => (
              <tr key={seriesTitle}>
                <td>{seriesTitle}</td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Container>
    </Layout>
  );
}
